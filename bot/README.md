# bot: Kitchen Buyer in Telegram

> Switched off on 2026-11-16, when the project closed (#2026): the bot and the speech-to-text
> service are no longer in `deploy/compose.yaml`, so no Telegram message is sent. The code is unchanged.

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

- Type or say a request: "20 L oat drink for Monday". One request may name several products:
  the gateway makes one proposal from it (#1375), and the bot shows it as a summary and one
  message per supplier with that supplier's lines.
- `/week`: the order for the menu plan of the next 7 days, all suppliers.
- `/brief` (or `/brief morning`, `/brief evening`): what waits and what is urgent, now. The first
  message has the products needed, the suppliers and the cost of all waiting orders (bold), the
  urgent lines (bold, set by the gateway's plain code), one line per supplier, then the other
  lines. Then one order message per supplier, 6 at most. The lines come from the gateway's brief
  route (#1332, wording by Nemotron, numbers checked there); the counts and totals are added up
  from the waiting proposals, and a total with an unknown part is not shown.
- `Add product` in a supplier's message: the first 6 rows of the proposal's addable list (counted
  products that are not on the order, most probable first), each with the engine's suggested
  quantity, or one lot when it has none. One press adds it; the gateway gives the new total.
- A question ("what does active recall mean?") is not sent to the Buyer. The bot explains its own
  words (recall, cut-off, stock not confirmed, supplier offer, delivery-note check) in plain code,
  or says that it cannot answer. A text with a number is always read as an order.
- After a change, the order's summary and the chat's last brief show the new numbers, also after a
  restart of the bot: the message ids are kept in the bot's volume.
- A photo of a shelf: Nemotron reads it (`POST /stock/photo`, which stores nothing) and the chat
  shows the count: counted rows, rows to count by hand, labels it did not recognise. `Save` sends
  only the counted rows to `POST /stock-counts`; `Discard` drops them. The bot never saves a count
  by itself, and a read is kept in memory only: after a restart, send the photo again.
- The same brief comes by itself at 07:00 and 16:00 Helsinki time to every linked chat
  (`BOT_BRIEF_TIMES`), once per slot also across a restart, and not later than 2 hours after its
  time. A brief with nothing in it makes no sound.
- `Change` on a supplier's message, then a line, then `−`, `+` or `Remove`. One step is the
  product's lot size. The gateway rounds, checks stock and gives the new total.
- `Open to approve` on the summary: our approval card. Approve and reject happen there,
  because both need a person. No approve scope exists for a token (`gateway/tokens.py`): the
  bot's token never approves.
