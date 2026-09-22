"""Entry point.

Everything is wired here and nowhere else: handlers receive what they need
through the dispatcher's workflow data rather than reaching for globals, which
is what makes them testable without a running bot.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import ConfigError, Settings, load_settings
from bot.handlers import admin, mode_formula, mode_situation, rating, start
from bot.middlewares.single_flight import SingleFlight
from bot.middlewares.user_context import UserContextMiddleware
from core.catalog import Catalog
from core.claude import ClaudeClient
from core.prompt.builder import PromptBuilder
from core.service import GenerationService
from db.session import make_engine, make_session_factory

logger = logging.getLogger(__name__)

#: The public command list. /export and /stats are deliberately absent — they
#: are owner-only, and listing them invites everyone to try.
COMMANDS = [
    BotCommand(command="formula", description="Собрать твист по формуле"),
    BotCommand(command="situation", description="Начать с описания ситуации"),
    BotCommand(command="limits", description="Сколько осталось на сегодня"),
    BotCommand(command="methodology", description="Методика целиком"),
    BotCommand(command="help", description="Как устроена формула"),
    BotCommand(command="cancel", description="Начать заново"),
]


def build_dispatcher(settings: Settings, service: GenerationService) -> Dispatcher:
    dispatcher = Dispatcher()

    dispatcher.workflow_data.update(
        settings=settings,
        service=service,
        sessions=service.sessions,
        single_flight=SingleFlight(),
    )

    context = UserContextMiddleware(service.sessions, settings.owner_telegram_id)
    dispatcher.message.middleware(context)
    dispatcher.callback_query.middleware(context)

    dispatcher.include_router(start.router)
    dispatcher.include_router(mode_formula.router)
    dispatcher.include_router(mode_situation.router)
    dispatcher.include_router(rating.router)
    dispatcher.include_router(admin.router)
    return dispatcher


def build_service(settings: Settings) -> GenerationService:
    """Assemble the service, failing fast on anything that is wrong on disk.

    ``verify()`` assembles every prompt profile once, so a missing methodology
    file or a redaction that no longer matches stops the bot at startup rather
    than on a user's first generation.
    """
    from anthropic import AsyncAnthropic

    builder = PromptBuilder(settings.profile)
    builder.verify()

    engine = make_engine(settings.database_url)
    return GenerationService(
        settings=settings,
        catalog=Catalog.load(),
        builder=builder,
        claude=ClaudeClient(
            messages=AsyncAnthropic(api_key=settings.anthropic_api_key).beta.messages,
            model=settings.model,
            effort=settings.generation_effort,
            max_tokens=settings.max_tokens,
            cache_system_prompt=settings.prompt_cache,
        ),
        sessions=make_session_factory(engine),
    )


async def run() -> None:
    settings = load_settings()
    service = build_service(settings)
    dispatcher = build_dispatcher(settings, service)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.set_my_commands(COMMANDS)

    logger.info(
        "starting: model=%s effort=%s profile=%s cache=%s",
        settings.model,
        settings.generation_effort,
        settings.profile.value,
        settings.prompt_cache,
    )
    await dispatcher.start_polling(bot)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run())
    except ConfigError as error:
        # A misconfiguration is the operator's to fix, and a stack trace would
        # only bury the one line that says which setting is wrong.
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
