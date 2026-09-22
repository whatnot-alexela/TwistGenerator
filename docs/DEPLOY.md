# Deployment

Written to be followed by someone who is not a programmer. Every command is
copy-paste; where a decision is needed it is called out.

Two things this document will not do: ask you to paste a secret anywhere it
could be read later, or let you skip the region check. The bot **must not** run
from a Russian IP — Anthropic does not serve the API there, and working around
it with a proxy puts the account at risk rather than solving anything
(docs/SPEC.md §5.2).

---

## 1. What to buy

| | |
|---|---|
| Provider | FirstByte, the same account you already have |
| Location | **Amsterdam, Finland or Germany — not Moscow** |
| Plan | KVM SSD, **2 GB RAM minimum**, 20 GB disk |
| OS | Ubuntu 24.04 LTS |
| Cost | roughly 400–600 ₽/month |

2 GB is not padding: Postgres and the bot together sit near 1 GB, and a build
on 1 GB will fail.

The methodology page stays on Timeweb where `kiloslov.ru` already lives. It is
a static page; nothing needs to change there except adding it.

---

## 2. Before you start, collect three things

1. **Bot token** — from [@BotFather](https://t.me/BotFather), `/mybots` →
   `@twist_generator` → API Token.
2. **Anthropic API key** — [console.anthropic.com](https://console.anthropic.com)
   → API Keys → Create Key. Set a **monthly spend limit of $150** on the
   account while you are there; it is the backstop behind the bot's own caps.
3. **Your Telegram id** — write to [@userinfobot](https://t.me/userinfobot), it
   replies with a number.

**Do not paste any of these into a chat, an email or a commit.** They go
straight onto the server in step 4 and nowhere else. If one leaks, revoke it:
BotFather can reissue the token, and the API key can be deleted in the console.

---

## 3. Prepare the server

Connect as root with the password the provider emailed:

```bash
ssh root@ВАШ_IP
```

Then, one block at a time:

```bash
# System packages
apt update && apt upgrade -y
apt install -y docker.io docker-compose-v2 git ufw

# Only SSH from outside. The bot needs no inbound ports — it polls Telegram.
ufw allow OpenSSH
ufw --force enable

# The code
mkdir -p /opt/twist && cd /opt/twist
git clone https://github.com/whatnot-alexela/TwistGenerator.git .
```

If the repository is private, GitHub will ask for credentials. Easiest is to
download a ZIP from the branch page and upload it with `scp` instead.

---

## 4. Configure

```bash
cd /opt/twist
cp .env.example .env
nano .env
```

Fill in the five values at the top. Everything below them already has a working
default.

```
BOT_TOKEN=            ← from BotFather
ANTHROPIC_API_KEY=    ← from the Anthropic console
OWNER_TELEGRAM_ID=    ← your number
DATABASE_URL=postgresql+asyncpg://twist:ПРИДУМАЙТЕ_ПАРОЛЬ@postgres:5432/twist
POSTGRES_PASSWORD=ТОТ_ЖЕ_ПАРОЛЬ   ← the same password, twice on purpose
```

Both places need the same password: one tells the bot how to connect, the
other is what the database is created with.

Save with `Ctrl+O`, `Enter`, then `Ctrl+X`.

Lock the file down — it now holds every secret you have:

```bash
chmod 600 .env
```

---

## 5. Start it

```bash
docker compose up -d --build
```

The first build takes a few minutes. Then check that all three parts came up:

```bash
docker compose ps
docker compose logs bot --tail 30
```

You want to see a line like:

```
starting: model=claude-opus-5 effort=high profile=full cache=False
```

If instead you see `Configuration error: …`, it names the setting that is
wrong. Fix `.env` and run `docker compose up -d` again.

---

## 6. The first real generation

This is the moment every cost figure in the specification stops being an
estimate.

Open [@twist_generator](https://t.me/twist_generator), send `/start`, and build
one twist with formula `6и-ФК`. Then send `/stats`.

Read the line **«В среднем за генерацию»**. Compare it with $0.25.

- **Close to $0.25** — the pack prices in `.env` stand.
- **Noticeably higher** — raise the pack prices before anyone can buy, or the
  packs lose money. The floor is 20 ⭐ per unit and the loader enforces it.
- **Noticeably lower** — you can lower the prices, or raise the free daily
  limits.

Do twenty generations across `1е` and `6и` before deciding: one generation
tells you very little, because the thinking length varies.

---

## 7. Backups

The database holds the ratings the methodology is being researched with.
Losing it loses the research, not just the service.

```bash
crontab -e
```

Add one line:

```
0 4 * * * cd /opt/twist && ./scripts/backup.sh >> backups/backup.log 2>&1
```

Fourteen daily dumps are kept. To copy them to your own machine:

```bash
scp root@ВАШ_IP:/opt/twist/backups/*.sql.gz ./
```

---

## 8. The methodology page

`METHODOLOGY_URL` in `.env` points at `https://kiloslov.ru`. Upload
`docs/methodology.html` from this repository to that hosting. It is generated
from the same text the bot runs on (`python scripts/build_page.py` rebuilds it),
so when an appendix is added, re-run the importer, re-run that, and upload the
new file — it is a single
self-contained file, no server side, nothing to install. Rename it to
`index.html` or place it wherever you prefer and update `METHODOLOGY_URL` to
match.

---

## Running it afterwards

| Task | Command |
|---|---|
| Watch the logs | `docker compose logs -f bot` |
| Restart | `docker compose restart bot` |
| Update to the latest code | `git pull && docker compose up -d --build` |
| Stop | `docker compose down` |
| Change a limit or a price | edit `.env`, then `docker compose restart bot` |
| Back up now | `./scripts/backup.sh` |

Migrations run automatically before the bot starts, so an update that changes
the database schema needs nothing extra from you.

---

## If something goes wrong

**The bot does not answer.** `docker compose logs bot --tail 50`. A
configuration error names its setting. Silence usually means the token is
wrong.

**«Сервис перегружен».** Anthropic is rate-limiting or the region is refusing
the request. Check that the server really is outside Russia:

```bash
curl -s https://ipinfo.io/country
```

It must not print `RU`.

**«Бот временно приостановил генерацию».** The emergency stop fired — $250 in
a month. Look at `/stats`, find out why, then raise `EMERGENCY_STOP_USD` if the
spend was legitimate.

**Generation is refused although nobody has used the bot.** The daily or
monthly free cap is counted against *recorded* spend, so a burst of failed
calls can exhaust it. `/stats` shows the failure count.

---

## Before the bot goes public

- [ ] Twenty real generations done, `/stats` read, §7 of the specification
      updated with the measured figures
- [ ] Pack prices re-derived from those figures
- [ ] `/export` run once, the file opened, the sheets checked
- [ ] Backups confirmed: `ls -la backups/` shows a file
- [ ] The methodology page opens at `kiloslov.ru`
- [ ] A spend limit set on the Anthropic account itself
