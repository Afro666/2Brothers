# bot: Kitchen Buyer in Telegram

A chef says or types what the kitchen needs. The bot shows the order as a summary message
and one message per supplier, takes changes, and opens our approval card for the approval.
It is a client of the gateway API (`docs/contract.md`) with a kitchen token: it has no
database and no model, and its token can never approve.

| File | What |
|---|---|
| `app.py` | The handlers and the long-polling loop (`python -m bot.app`). |
| `render.py` | Proposal to messages. Pure functions; the message rules are at its top. |
| `clients.py` | Telegram's Bot API, our gateway, the speech-to-text service. |
| `links.py` | Which chats are linked, and the one-time codes (`python -m bot.links`). |
| `stt_service.py` | Whisper on our own server: one voice message to text (#1331). |

## Message rules

- First a summary message, then one message per supplier. Never one message per product.
- The first line says the one thing that matters, in bold.
- Bold only: the counts and total of a first line, a supplier's total, a deadline.
- A tap edits the message in place. At most two rows of buttons.
- Every number is copied from the proposal. The bot computes no price and no total.
- No product codes when the name is known. Unknown is said in words ("stock not confirmed").

## Keys (names in `.env.example`)

| Key | What |
|---|---|
| `TELEGRAM_BOT` | The token from BotFather. |
| `BOT_KITCHEN_TOKEN` | A kitchen API token with `kitchen:read` and `kitchen:propose` (Settings > API & MCP tokens). |
| `BOT_KITCHEN_ID` | The kitchen of that token. Default `demo-kitchen`. |
| `BOT_GATEWAY_URL` | `http://gateway:8000` on the server; `https://<site>/gateway` from a laptop. |
| `BOT_SITE_URL` | The site, for the "Open to approve" button. |
| `BOT_STT_URL` | `http://stt:8002` on the server. Empty: the bot says it cannot listen. |

Without `TELEGRAM_BOT`, `BOT_GATEWAY_URL` or `BOT_KITCHEN_TOKEN` the bot says so once and
stays idle.

## Link a chat

`python -m bot.links <bot username>` prints a link that works once, for 30 minutes. The
person opens it in Telegram and presses Start. Only linked chats get an answer.

## What a person can do

- Type or say a request: "20 L oat drink for Monday". One product per message until #1375.
- `/week`: the order for the menu plan of the next 7 days, all suppliers.
- `Change` on a supplier's message, then a line, then `−`, `+` or `Remove`. One step is the
  product's lot size. The gateway rounds, checks stock and gives the new total.
- `Open to approve` on the summary: our approval card. Approve and reject happen there,
  because both need a person (`kitchen:approve`).
