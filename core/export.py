"""The owner's view of the data: `/export` and `/stats`.

Two jobs. `Stats` answers "what is this costing me and is it any good" in a
message. `build_workbook` writes the whole dataset out so the author can read
it in a spreadsheet — this is the research output the ratings exist for.

Money is carried as ``Decimal`` all the way to the cell. Rounding it earlier to
make the arithmetic easier would quietly disagree with the ledger the caps are
enforced against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, Final

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.formula import CHANGE_KINDS, CHANGE_TYPES, Formula, FormulaError
from db.models import ApiCall, BudgetLedger, Generation, Payment, Rating, User

#: Excel refuses these in a cell; the methodology's text has none of them today,
#: but a user-written comment easily could.
_ILLEGAL: Final[str] = "".join(chr(code) for code in (*range(0, 9), 11, 12, *range(14, 32)))
_SCRUB: Final[dict[int, None]] = dict.fromkeys(map(ord, _ILLEGAL))

HEADER: Final[Font] = Font(bold=True)


@dataclass
class Stats:
    """What `/stats` reports."""

    generations: int = 0
    users: int = 0
    rated: int = 0
    average_score: Decimal | None = None
    spend_today: Decimal = Decimal("0")
    spend_month: Decimal = Decimal("0")
    spend_total: Decimal = Decimal("0")
    tokens_in: int = 0
    tokens_out: int = 0
    failures: int = 0
    cache_reads: int = 0

    @property
    def average_cost(self) -> Decimal | None:
        """The number that replaces the estimate in docs/SPEC.md §7.1."""
        if not self.generations:
            return None
        return self.spend_total / self.generations


async def collect_stats(session: AsyncSession, today: date) -> Stats:
    stats = Stats()
    stats.generations = await session.scalar(select(func.count()).select_from(Generation)) or 0
    stats.users = await session.scalar(select(func.count()).select_from(User)) or 0
    stats.rated = await session.scalar(select(func.count()).select_from(Rating)) or 0

    average = await session.scalar(select(func.avg(Rating.score)))
    if average is not None:
        stats.average_score = Decimal(str(average)).quantize(Decimal("0.01"))

    totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(ApiCall.cost_usd), 0),
                func.coalesce(func.sum(ApiCall.input_tokens), 0),
                func.coalesce(func.sum(ApiCall.output_tokens), 0),
                func.coalesce(func.sum(ApiCall.cache_read_input_tokens), 0),
            )
        )
    ).one()
    stats.spend_total = Decimal(str(totals[0]))
    stats.tokens_in = int(totals[1])
    stats.tokens_out = int(totals[2])
    stats.cache_reads = int(totals[3])

    stats.failures = (
        await session.scalar(
            select(func.count()).select_from(ApiCall).where(ApiCall.error.is_not(None))
        )
        or 0
    )

    day = await session.scalar(
        select(BudgetLedger.free_spend_usd + BudgetLedger.paid_spend_usd).where(
            BudgetLedger.period_date == today
        )
    )
    stats.spend_today = Decimal(str(day)) if day is not None else Decimal("0")

    month = await session.scalar(
        select(
            func.coalesce(func.sum(BudgetLedger.free_spend_usd + BudgetLedger.paid_spend_usd), 0)
        ).where(
            BudgetLedger.period_date >= today.replace(day=1),
            BudgetLedger.period_date <= today,
        )
    )
    stats.spend_month = Decimal(str(month))
    return stats


# --------------------------------------------------------------------------- #
# The workbook
# --------------------------------------------------------------------------- #


def _clean(value: Any) -> Any:
    """Make a value safe for a cell without losing what it says."""
    if isinstance(value, str):
        text = value.translate(_SCRUB)
        # Excel's hard limit. Truncating is better than a file that will not
        # open, and the marker makes the truncation visible rather than silent.
        return text if len(text) <= 32_000 else text[:32_000] + " …[обрезано]"
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return value


def _sheet(book: Workbook, title: str, headers: list[str], rows: list[list[Any]]) -> None:
    sheet = book.create_sheet(title)
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = HEADER
        cell.alignment = Alignment(vertical="top")
    for row in rows:
        sheet.append([_clean(value) for value in row])

    sheet.freeze_panes = "A2"
    for index, header in enumerate(headers, start=1):
        width = max(len(header) + 2, 12)
        sheet.column_dimensions[get_column_letter(index)].width = min(width, 40)


@dataclass
class ExportFilter:
    since: date | None = None
    until: date | None = None

    def apply(self, statement: Any, column: Any) -> Any:
        if self.since:
            statement = statement.where(column >= self.since)
        if self.until:
            statement = statement.where(column <= self.until)
        return statement


@dataclass
class Export:
    filename: str
    data: bytes
    rows: dict[str, int] = field(default_factory=dict)


async def build_workbook(
    session: AsyncSession, today: date, window: ExportFilter | None = None
) -> Export:
    window = window or ExportFilter()
    book = Workbook()
    book.remove(book.active)
    counts: dict[str, int] = {}

    # -- generations, joined with their rating and their cost --------------- #
    cost_by_generation = (
        select(ApiCall.generation_id, func.sum(ApiCall.cost_usd).label("cost"))
        .where(ApiCall.generation_id.is_not(None))
        .group_by(ApiCall.generation_id)
        .subquery()
    )
    statement = (
        select(Generation, Rating, User.telegram_id, User.username, cost_by_generation.c.cost)
        .join(User, Generation.user_id == User.id)
        .outerjoin(Rating, Rating.generation_id == Generation.id)
        .outerjoin(cost_by_generation, cost_by_generation.c.generation_id == Generation.id)
        .order_by(Generation.created_at)
    )
    rows: list[list[Any]] = []
    for generation, rating, telegram_id, username, cost in (
        await session.execute(window.apply(statement, func.date(Generation.created_at)))
    ).all():
        rows.append(
            [
                generation.id,
                generation.created_at,
                telegram_id,
                username,
                generation.mode,
                generation.formula,
                CHANGE_TYPES.get(generation.change_type, ""),
                CHANGE_KINDS.get(generation.change_kind, ""),
                _paradox_label(generation),
                generation.catalogued,
                generation.had_reference,
                generation.genre,
                generation.characters,
                generation.setting,
                generation.user_expectation,
                generation.expectation_adapted,
                generation.profile,
                generation.model,
                generation.effort,
                generation.was_free,
                generation.units_charged,
                float(cost) if cost is not None else None,
                rating.score if rating else None,
                rating.comment if rating else None,
                generation.example_seed,
                generation.response_text,
            ]
        )
    counts["generations"] = len(rows)
    _sheet(
        book,
        "generations",
        [
            "id",
            "время",
            "telegram_id",
            "username",
            "режим",
            "формула",
            "тип изменения",
            "вид",
            "парадокс",
            "есть пример",
            "есть фильм/книга",
            "жанр",
            "персонажи",
            "сеттинг",
            "ситуация",
            "ожидание переписано",
            "профиль",
            "модель",
            "effort",
            "бесплатно",
            "единиц",
            "стоимость $",
            "оценка",
            "комментарий",
            "seed",
            "текст твиста",
        ],
        rows,
    )

    # -- ratings, grouped the three ways worth looking at -------------------- #
    rows = []
    by_formula = (
        await session.execute(
            select(
                Generation.formula,
                func.count(Rating.id),
                func.avg(Rating.score),
            )
            .join(Rating, Rating.generation_id == Generation.id)
            .group_by(Generation.formula)
            .order_by(func.avg(Rating.score).desc())
        )
    ).all()
    for formula, count, average in by_formula:
        rows.append(["формула", formula, count, round(float(average), 2)])

    for label, column in (
        ("парадокс №1", Generation.paradox_1),
        ("парадокс №2", Generation.paradox_2),
    ):
        for value, count, average in (
            await session.execute(
                select(column, func.count(Rating.id), func.avg(Rating.score))
                .join(Rating, Rating.generation_id == Generation.id)
                .group_by(column)
            )
        ).all():
            rows.append([label, "есть" if value else "нет", count, round(float(average), 2)])

    for mode, count, average in (
        await session.execute(
            select(Generation.mode, func.count(Rating.id), func.avg(Rating.score))
            .join(Rating, Rating.generation_id == Generation.id)
            .group_by(Generation.mode)
        )
    ).all():
        rows.append(["режим", mode, count, round(float(average), 2)])

    for catalogued, count, average in (
        await session.execute(
            select(Generation.catalogued, func.count(Rating.id), func.avg(Rating.score))
            .join(Rating, Rating.generation_id == Generation.id)
            .group_by(Generation.catalogued)
        )
    ).all():
        rows.append(["есть пример", "да" if catalogued else "нет", count, round(float(average), 2)])

    counts["ratings"] = len(rows)
    _sheet(book, "ratings", ["разрез", "значение", "оценок", "средняя"], rows)

    # -- costs, per day ------------------------------------------------------ #
    rows = []
    for ledger in (
        await session.scalars(
            window.apply(
                select(BudgetLedger).order_by(BudgetLedger.period_date), BudgetLedger.period_date
            )
        )
    ).all():
        rows.append(
            [
                ledger.period_date,
                float(ledger.free_spend_usd),
                float(ledger.paid_spend_usd),
                float(ledger.free_spend_usd + ledger.paid_spend_usd),
            ]
        )
    counts["costs"] = len(rows)
    _sheet(book, "costs", ["дата", "бесплатно $", "платно $", "всего $"], rows)

    # -- api calls, the raw record the estimates get replaced from ----------- #
    rows = []
    for call in (
        await session.scalars(
            window.apply(
                select(ApiCall).order_by(ApiCall.created_at), func.date(ApiCall.created_at)
            )
        )
    ).all():
        rows.append(
            [
                call.created_at,
                call.generation_id,
                call.purpose,
                call.model,
                call.effort,
                call.input_tokens,
                call.output_tokens,
                call.cache_creation_input_tokens,
                call.cache_read_input_tokens,
                float(call.cost_usd),
                call.was_free,
                call.latency_ms,
                call.stop_reason,
                call.error,
            ]
        )
    counts["api_calls"] = len(rows)
    _sheet(
        book,
        "api_calls",
        [
            "время",
            "generation_id",
            "назначение",
            "модель",
            "effort",
            "вход",
            "выход",
            "кэш записано",
            "кэш прочитано",
            "стоимость $",
            "бесплатно",
            "мс",
            "stop_reason",
            "ошибка",
        ],
        rows,
    )

    # -- users --------------------------------------------------------------- #
    generation_counts = (
        select(Generation.user_id, func.count().label("total"))
        .group_by(Generation.user_id)
        .subquery()
    )
    paid_totals = (
        select(Payment.user_id, func.sum(Payment.stars).label("stars"))
        .group_by(Payment.user_id)
        .subquery()
    )
    rows = []
    for user, total, stars in (
        await session.execute(
            select(User, generation_counts.c.total, paid_totals.c.stars)
            .outerjoin(generation_counts, generation_counts.c.user_id == User.id)
            .outerjoin(paid_totals, paid_totals.c.user_id == User.id)
            .order_by(User.created_at)
        )
    ).all():
        rows.append(
            [
                user.telegram_id,
                user.username,
                user.first_name,
                user.is_owner,
                user.is_blocked,
                total or 0,
                user.paid_units,
                int(stars) if stars else 0,
                user.created_at,
                user.last_seen_at,
            ]
        )
    counts["users"] = len(rows)
    _sheet(
        book,
        "users",
        [
            "telegram_id",
            "username",
            "имя",
            "владелец",
            "заблокирован",
            "генераций",
            "осталось единиц",
            "куплено ⭐",
            "первый вход",
            "последний",
        ],
        rows,
    )

    buffer = BytesIO()
    book.save(buffer)
    suffix = ""
    if window.since or window.until:
        suffix = f"_{window.since or 'начало'}_{window.until or today}"
    return Export(
        filename=f"twist_export_{today}{suffix}.xlsx", data=buffer.getvalue(), rows=counts
    )


def _paradox_label(generation: Generation) -> str:
    if generation.paradox_1 and generation.paradox_2:
        return "оба"
    if generation.paradox_1:
        return "№1"
    if generation.paradox_2:
        return "№2"
    return "нет"


def parse_window(args: list[str]) -> ExportFilter:
    """``/export 2026-09-01 2026-09-30`` — both bounds optional."""
    window = ExportFilter()
    for index, raw in enumerate(args[:2]):
        try:
            parsed = date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"не похоже на дату: {raw}") from exc
        if index == 0:
            window.since = parsed
        else:
            window.until = parsed
    if window.since and window.until and window.since > window.until:
        raise ValueError("начальная дата позже конечной")
    return window


def validate_formula(code: str) -> Formula:
    """Used by the owner tooling; surfaces the parser's own message."""
    try:
        return Formula.parse(code)
    except FormulaError as exc:
        raise ValueError(str(exc)) from exc
