# The bot runs outside Russia — the Anthropic API does not serve it from there.
# See docs/SPEC.md §5.2 and docs/DEPLOY.md.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "aiogram>=3.15" "anthropic>=0.40" "sqlalchemy[asyncio]>=2.0" \
    "asyncpg>=0.30" "alembic>=1.14" "pyyaml>=6.0" "openpyxl>=3.1"

COPY core/ ./core/
COPY bot/ ./bot/
COPY db/ ./db/
COPY migrations/ ./migrations/
COPY methodology/ ./methodology/
COPY alembic.ini ./

# Never run as root: a container escape should not land on a root shell.
RUN useradd --create-home --uid 10001 twist && chown -R twist:twist /app
USER twist

# Fails fast on a missing methodology file or a redaction that no longer
# matches, rather than on a user's first generation.
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "from core.prompt.builder import PromptBuilder; PromptBuilder().verify()"

CMD ["python", "-m", "bot.main"]
