"""Every word the user reads, in one place.

No user-facing string belongs anywhere else in the codebase: the author edits
his own bot's voice here, without reading Python.

The formula card is assembled by :func:`formula_card` rather than written out
per case, because the three coverage states differ by only a paragraph and
keeping them side by side is what stops them drifting apart.
"""

from __future__ import annotations

from typing import Any, Final

from core.catalog import Coverage, Slice
from core.formula import CAUSES, CHANGE_KINDS, CHANGE_TYPES, Formula, ParadoxVerdict

START: Final[str] = (
    "<b>Генератор сюжетных твистов</b>\n\n"
    "Строит сюжетные повороты по методике «Генератор твистов 1.0» — "
    "188 формул на основе четырёх причин Аристотеля и шести типов изменения.\n\n"
    "Твист собирается не наугад: вы задаёте формулу, и бот строит поворот "
    "строго по ней.\n\n"
    "С чего начнём?"
)

HELP: Final[str] = (
    "<b>Как устроена формула</b>\n\n"
    "Формула выглядит так: <code>1е-ФД</code>.\n\n"
    "<b>Первая цифра</b> — что меняется в сюжете: 1 Место, 2 Качество, "
    "3 Рост, 4 Убыль, 5 Возникновение, 6 Исчезновение.\n\n"
    "<b>Буква е или и</b> — как это воспринимается в начале: «е» естественное "
    "(судьба, природа, случай), «и» искусственное (чья-то воля). Важно: вид "
    "определяется по тому, как ситуация выглядит <i>до</i> поворота.\n\n"
    "<b>Две последние буквы</b> — причины. Первая: та, которую все считают "
    "настоящей. Вторая: та, которая раскрывается на самом деле. "
    "Ф Формальная (замысел), М Материальная (ресурс), Д Действующая "
    "(исполнитель), К Конечная (цель).\n\n"
    "Так <code>1е-ФД</code> читается: перемещение, которое выглядит "
    "естественным; думали — дело в природе вещей, оказалось — кто-то "
    "действовал.\n\n"
    "Сгенерированные твисты и ваши оценки сохраняются — они нужны автору "
    "методики для её развития."
)

CHOOSE_CHANGE_TYPE: Final[str] = "<b>Шаг 1 из 4.</b> Что меняется в сюжете?"
CHOOSE_CHANGE_KIND: Final[str] = (
    "<b>Шаг 2 из 4.</b> Как это выглядит <i>в начале</i>, до поворота?\n\n"
    "Это важное правило методики: вид изменения определяется по Ожиданию, "
    "а не по тому, чем всё окажется."
)
CHOOSE_CAUSE_1: Final[str] = (
    "<b>Шаг 3 из 4.</b> Какую причину все считают настоящей?\n\n"
    "Это то, во что верят персонажи и читатель до поворота."
)
CHOOSE_CAUSE_2: Final[str] = (
    "<b>Шаг 4 из 4.</b> Что раскроется на самом деле?\n\n"
    "Рядом с каждой причиной — какой парадокс получится."
)

UNRESEARCHED: Final[str] = (
    "🎉 <b>Ура, вы нашли малоисследованный твист!</b>\n"
    "Пример в методике есть, а вот реализаций в кино и литературе автор не нашёл."
)

UNCATALOGUED: Final[str] = (
    "📋 Приложение с примерами для этой группы ещё не написано — "
    "готовы только <code>1е</code> и <code>6и</code>.\n"
    "Твист всё равно будет построен, строго по правилам методики."
)

OPTIONS: Final[str] = (
    "Можно добавить условия — или сразу генерировать.\n\nЧем конкретнее условия, тем точнее твист."
)

ASK_GENRE: Final[str] = "Напишите жанр. Не больше 64 символов."
ASK_CHARACTERS: Final[str] = "Опишите персонажей. Не больше 300 символов."
ASK_SETTING: Final[str] = "Сеттинг или эпоха. Не больше 100 символов."
ASK_COMMENT: Final[str] = "Напишите, что не так или что понравилось. Не больше 500 символов."

GENERATING: Final[str] = "Собираю твист. Это занимает около минуты."

RATE: Final[str] = "Насколько удачно получилось?"
RATED: Final[str] = "Спасибо, оценка записана."
COMMENT_SAVED: Final[str] = "Записал, спасибо."

TOO_LONG: Final[str] = (
    "Слишком длинно: {length} символов при лимите {limit}. Сократите, пожалуйста."
)

ALREADY_RUNNING: Final[str] = "Генерация уже идёт — дождитесь результата."

DENIED_DAILY_LIMIT: Final[str] = (
    "На сегодня бесплатные генерации закончились.\n\n"
    "Приходите завтра — лимит обновится в полночь по Москве. "
    "Или купите пакет: /buy"
)
DENIED_BUDGET: Final[str] = (
    "Бесплатные генерации на сегодня исчерпаны по всему боту — "
    "не вами, а общим дневным лимитом.\n\n"
    "Приходите завтра или купите пакет: /buy"
)
DENIED_EMERGENCY: Final[str] = (
    "Бот временно приостановил генерацию. Это не ваша вина — автор уже уведомлён. Попробуйте позже."
)
DENIED_BLOCKED: Final[str] = "Доступ к боту закрыт."

ERROR_UNAVAILABLE: Final[str] = (
    "Сервис перегружен и не ответил. Попробуйте через минуту — генерация не списана."
)
ERROR_REFUSED: Final[str] = (
    "Не удалось сгенерировать твист по этой формуле с такими условиями. "
    "Попробуйте изменить жанр или описание персонажей.\n\n"
    "Генерация не списана."
)
ERROR_GENERIC: Final[str] = (
    "Что-то сломалось на нашей стороне. Автор уведомлён, генерация не списана."
)

CANCELLED: Final[str] = "Отменил. Начать заново: /formula"

#: One line per verdict for the formula card. The prompt gets a fuller version
#: (core/prompt/slice.py) — this is what the user reads.
PARADOX_CARD: Final[dict[ParadoxVerdict, str]] = {
    ParadoxVerdict.NONE: (
        "⚪️ <b>Парадокса нет.</b> Обе причины «свои» для этого вида изменения — "
        "твист работает чистой подменой причины."
    ),
    ParadoxVerdict.PARADOX_1: (
        "🔵 <b>Парадокс №1</b> — противоречие видно с самого начала.\n"
        "Читатель чувствует, что что-то не сходится, ещё до поворота. "
        "Откровение объясняет, почему странность была."
    ),
    ParadoxVerdict.PARADOX_2: (
        "🟣 <b>Парадокс №2</b> — почва уходит из-под ног.\n"
        "До поворота всё безупречно логично. Откровение не объясняет "
        "странность, а создаёт её, переворачивая картину мира."
    ),
    ParadoxVerdict.BOTH: (
        "🔵🟣 <b>Оба парадокса сразу.</b>\n"
        "Диссонанс различим с самого начала — и при этом уводит не туда. "
        "Самая сложная в исполнении группа формул."
    ),
}

#: Shown next to each option at step 4, so the choice is made knowingly.
PARADOX_HINT: Final[dict[ParadoxVerdict, str]] = {
    ParadoxVerdict.NONE: "без парадокса",
    ParadoxVerdict.PARADOX_1: "Парадокс №1",
    ParadoxVerdict.PARADOX_2: "Парадокс №2",
    ParadoxVerdict.BOTH: "оба парадокса",
}


def formula_card(formula: Formula, catalogue: Slice) -> str:
    """The card shown once a formula is complete."""
    parts = [
        f"<b>{formula.code}</b>",
        "",
        f"{CHANGE_TYPES[formula.change_type]}, {CHANGE_KINDS[formula.change_kind]} изменение.",
        f"Ожидание: {CAUSES[formula.cause_1]} причина → Откровение: {CAUSES[formula.cause_2]}.",
        "",
        PARADOX_CARD[formula.paradox],
    ]

    if catalogue.coverage is Coverage.UNCATALOGUED:
        parts += ["", UNCATALOGUED]
        return "\n".join(parts)

    if catalogue.example is not None:
        parts += [
            "",
            "<b>Пример из методики</b>",
            f"<i>Ожидание:</i> {catalogue.example.expectation}",
            f"<i>Откровение:</i> {catalogue.example.revelation}",
        ]

    if catalogue.reference is not None:
        parts += ["", f"<b>{catalogue.reference.label}</b>", catalogue.reference.analysis]
        if catalogue.reference.note:
            parts.append(f"<i>{catalogue.reference.note}</i>")
    else:
        parts += ["", UNRESEARCHED]

    return "\n".join(parts)


def limits(free_formula: int, free_expectation: int, paid: int) -> str:
    return (
        "<b>Осталось на сегодня</b>\n\n"
        f"По формуле: {free_formula}\n"
        f"По описанию ситуации: {free_expectation}\n"
        f"Оплачено: {paid}\n\n"
        "Бесплатные обновляются в полночь по Москве."
    )


EXPORT_EMPTY: Final[str] = "Выгружать пока нечего — ни одной генерации."

EXPORT_BAD_DATES: Final[str] = (
    "{error}\n\nФормат: <code>/export 2026-09-01 2026-09-30</code>. Обе даты можно не указывать."
)


def export_caption(rows: dict[str, int]) -> str:
    return (
        "Выгрузка готова.\n"
        f"Генераций: {rows.get('generations', 0)}\n"
        f"Вызовов к API: {rows.get('api_calls', 0)}\n"
        f"Пользователей: {rows.get('users', 0)}"
    )


def stats(figures: Any) -> str:
    """The owner's dashboard. The average cost is the line that matters: it is
    what replaces the estimate the pack prices were built on."""
    lines = [
        "<b>Статистика</b>",
        "",
        f"Генераций: {figures.generations}",
        f"Пользователей: {figures.users}",
    ]
    if figures.rated:
        share = round(figures.rated / figures.generations * 100) if figures.generations else 0
        lines.append(f"Оценено: {figures.rated} ({share}%), средняя {figures.average_score}")
    else:
        lines.append("Оценок пока нет")

    lines += [
        "",
        "<b>Деньги</b>",
        f"Сегодня: ${figures.spend_today:.2f}",
        f"За месяц: ${figures.spend_month:.2f} из $100",
        f"Всего: ${figures.spend_total:.2f}",
    ]
    if figures.average_cost is not None:
        lines.append(f"<b>В среднем за генерацию: ${figures.average_cost:.3f}</b>")
        lines.append("<i>Оценка в спецификации — $0.25. Сверьте.</i>")

    lines += [
        "",
        f"Токенов: {figures.tokens_in:,} вход / {figures.tokens_out:,} выход".replace(",", " "),
    ]
    if figures.cache_reads:
        lines.append(f"Прочитано из кэша: {figures.cache_reads:,}".replace(",", " "))
    if figures.failures:
        lines.append(f"Неудачных вызовов: {figures.failures}")

    return "\n".join(lines)


def methodology(url: str) -> str:
    return (
        f"<b>Методика «Генератор твистов 1.0»</b>\n\nПолный текст, все 188 формул и примеры:\n{url}"
    )
