# Backlog

Improvements the author asked for after the bot went live. Each entry says what
it costs — his money, his time, or mine — because that is what decides the
order.

---

## 1. The first screen is not a blank chat

**Now.** A user who has met the bot before opens the chat and sees nothing: the
`/start` screen is behind a command they have to remember.

**Change.** Three pieces, smallest first:

- A **persistent button** at the bottom of the chat («✨ Начать»), always
  visible, which opens the same menu `/start` does. This is the one that
  actually solves it.
- The **description in BotFather** — the text shown to someone who has never
  started the bot, above the START button. Costs nothing but a paste.
- `/start` **stays** where it is, for anyone who types it.

**Cost.** About an hour. No effect on the bill. One risk worth naming: a
persistent keyboard takes screen space on a phone permanently, so the button
must be a single short row.

---

## 2. Cause letters carry their meaning

**Now.** The buttons read `Ф · Формальная`, which means nothing to a reader who
has not yet read the methodology.

**Change.** Add the plain-language gloss already used in `/help`:

| | |
|---|---|
| Ф | Формальная (замысел) |
| М | Материальная (ресурс) |
| Д | Действующая (исполнитель) |
| К | Конечная (цель) |

**Where.** On the first-cause buttons and the manual-choice buttons. **Not** on
the second-cause buttons — those already carry the paradox hint, and on a phone
the label would wrap to three lines. There the gloss goes into the message
above the buttons instead.

**Cost.** Half an hour.

---

## 3. Consent to data processing

**Now.** The bot stores a Telegram id, everything the user types into a
generation, and their ratings. Nobody is asked.

**Change.**

- A consent screen before the first generation: what is stored, why, for how
  long, and a link to the full text. One button to agree; without it the bot
  explains and does not generate.
- Consent recorded per user — the fact, the moment, and the version of the text
  agreed to. A later version means asking again.
- A policy page, published next to the methodology on `kiloslov.ru`.
- A way out: a command that deletes the user's data on request.

**What I need from the author** before writing the text:

1. **Who the operator is** — the name that appears in the policy as the person
   responsible. A private individual's full name becomes public on that page;
   that is the trade-off, and it is his call.
2. **A contact** for data requests — an email is enough, and it should not be
   his personal one if he would rather it were not public.

**Cost.** Half a day: the text, the screen, the database column, the deletion
path, the page. The ratings the research depends on keep arriving either way —
consent does not reduce what is stored, it makes it asked for.

**Worth saying plainly:** I can write a policy that covers what this bot
actually does, in the shape these texts normally take. I am not a lawyer, and
this is not legal advice. If the bot is ever going to carry his name
commercially, the text deserves twenty minutes of a real one's time.
