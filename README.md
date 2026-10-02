# Memoranda

**A field-work notebook for small service businesses.** Turn everyday notes into a customer and job ledger: track equipment, work, payments, balances, and follow-up reminders from a web notebook or Telegram. Walrus Memory (MemWal) stores append-only records; the app derives the current view from those records rather than treating an AI reply as the ledger.

> **Prototype notice:** This is a competition prototype, not production accounting software. Do not enter real customer data into a self-hosted copy unless you understand and accept the security, backup, availability, and data-retention limits below.

## Try it

| Channel | Where | How to start |
|---|---|---|
| Web notebook | <https://mistakes-wind-flour-imported.trycloudflare.com> | The landing page is `/`; the notebook itself is `/app`. Choose **Create new**, then keep the passkey it shows you. |
| Telegram | [@memorandachatbot](https://t.me/memorandachatbot) | Send `/help` for the command list, or `/new` to create a book and bind this chat to it. |

Both channels talk to the same book. A note written in the web notebook is visible
in Telegram and the other way round, because both call one API over one MemWal
namespace.

Two honest caveats before you click:

- The web link is a **Cloudflare quick tunnel**. It rotates whenever the tunnel
  process restarts and is unreachable while the host is down, so treat it as a
  demo that may be offline rather than a hosted service. If it does not load,
  [run it locally](#run-locally) instead.
- The Telegram bot is bound to the same demo account and is shared. Create your
  own book with `/new`; do not put real customer names in it.

## What it does

- Create a private book without an account or wallet; reopen it with its passkey.
- Record service jobs, customer payments, and balances from natural-language notes.
- Ask questions such as “How much does Budi still owe?” or “When was the AC last serviced?” Answers are derived from the recorded book state.
- Ask to be reminded at a specific time. The Telegram bot checks for due reminders and sends them to a bound chat; reminder times use the book's IANA timezone (new books default to `Asia/Jakarta`).
- Use the same book from the browser and Telegram. Telegram is an optional channel and must be configured and bound separately.
- Tell which book you are looking at, so two books are not mistaken for each other: the shop name is shown in the page header, on `/book` and `/remind` replies, and on every delivered reminder.
- Select Indonesian or English per book. Other language names can be supplied, but the parser's handwritten behavior has not been verified for them. Currency (IDR/USD) and timezone are independent book settings.
- Queue writes locally while MemWal is slow or rate-limited. The UI can reflect queued records before the remote write lands.

## How it works

Two ways in, one book behind both. Neither channel is a second ledger: the web page and the bot call the same server API, and one book is one MemWal namespace.

**What happens to a message.** Write the note the way you would say it to a person. `parse.py` asks the configured model to propose a structured record (who, what, how much, what was paid, when they promised to pay). Deterministic validation and `packlib.py` then decide what is accepted and calculate the balances, so the model never writes the ledger. A number that is genuinely ambiguous is asked about rather than guessed. The reply says what was recorded, which makes a wrong reading visible while the sentence is still in front of you.

**Reminders, and the two kinds.** A payment promise creates a **collect** reminder for the promised time. An **offer-again** reminder, for calling a customer back in a few months, is only created when you ask for it, because a book that invents follow-ups is a book you stop trusting. The bot's reminder loop wakes every 45 seconds, sends what is due, writes a `fired` record, and keeps a local marker so a restart cannot deliver the same reminder twice. At most three reminders go to one chat per pass, and reminders more than 30 days old are not sent. A reminder keeps the timezone it was created under. Delivery needs the bot process running with that chat bound to that book.

**The derived view.** Nothing is edited in place. A correction is a newer record, and the customer balances, the reminder list, and the answers all get recomputed from the records on each read. That is why a settled customer stops appearing as owed, and why the same book reads the same on the web page and in Telegram.

### Telegram commands

The bot answers any message, so a command is only needed for the few things that are not a note. Both spellings work whichever language the book speaks: the English name is shown first, the Indonesian alias is accepted silently. The list below is what `/help` prints, and it is generated from `commands.py`, so it cannot describe a command that does not exist.

| Command | Also accepted | What it does |
|---|---|---|
| `/start` | `/mulai` | Prints the same list as `/help`. |
| `/help` | `/bantuan`, `/tolong` | Prints the command list with one line each. |
| `/new` | `/baru` | Creates a book and replies with its key. |
| `/key` | `/kunci` | Connects this chat to a book you already have. Write `/key <passkey>`, or paste the key on its own as the next message. |
| `/book` | `/buku`, `/buku_ku` | Shows what is in the book now: each customer with their balance, and the reminders waiting. |
| `/remind` | `/ingat`, `/ingatkan` | Shows only the scheduled reminders. |
| `/timezone` | `/zona` | Shows the book timezone in use. |
| `/release` | `/lepas`, `/keluar` | Unbinds this chat. The book itself stays on Walrus. |

One chat is bound to one book at a time. `/book`, `/remind`, and every reminder open with the shop name, because a message can arrive hours after the one before it and still has to say which book it came from. Do not put a private book's bot into a public group.

## Product screenshots

Reviewed captures live in [`docs/images/`](docs/images/). Each one was read back at
full size with OCR before it was kept, and no capture shows a book key, bot token,
chat id, or real customer record. Names, amounts, and dates in them are fictional
demo records.

| File | What it shows |
|---|---|
| `homepage.png` | The English landing page served at `/`, including its note that this is a prototype for the session. |
| `notebook-demo.jpg` | Job notes, the customer balances derived from them, and the scheduled reminders for one demo shop. |
| `cross-session-memory.png` | The same book opened on the web channel and asked about a settled customer whose record was made through the Telegram bot. The chat holds one question and one answer, the amount is not printed anywhere else on the page, and the header names the shop. |
| `reminder-notification.jpg` | The Telegram chat with the bot: a reminder list, the acknowledgement for a newly recorded job, and the reminder that arrived afterwards carrying the shop name. The bot name is visible, and no account name or number is in frame. |

`create-book.png` is not captured, and is not required: the book-creation form is
reachable from `/app` and adds little that `notebook-demo.jpg` does not already show.

Use a dedicated demo book and fictional names, dates, amounts, and chat. Never publish a passkey, bot token, phone number, real customer record, private chat ID, or production log. Runtime files in `data/` are not documentation material. See [`docs/images/README.md`](docs/images/README.md) for the capture checklist.

## Architecture

```text
Browser ─┐
         ├── HTTP API (server.py) ── parser/validator ── MemWal (Walrus Memory)
Telegram ┘       │                         │
                 └── local journal + outbox┘
       Telegram reminder loop polls the API and sends due notifications
```

`parse.py` asks the configured model to interpret a note. Deterministic validation and `packlib.py` decide which records are accepted and calculate balances/reminder views. The model does not write the ledger directly. The web app and Telegram bot use the same server API; the bot is an adapter, not a second ledger implementation.

## Run locally

### Requirements

- Python 3.11+ (the code uses `zoneinfo`); dependencies are pinned in `requirements.txt`.
- A valid MemWal account/delegate key and account ID, plus network access to the configured relayer/Walrus Memory service.
- A model API key compatible with the OpenAI chat-completions API. Defaults: `https://api.deepseek.com` and `deepseek-chat`.
- For Telegram notifications, a Telegram bot token from BotFather.

Create an isolated environment and install the checked-in dependencies:

```bash
cd /path/to/fieldpack
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Edit `.env` with credentials for your own setup. **Do not commit `.env` or put real values in shell history.** Both processes load `.env` from the project directory and nothing else; if your secrets live in a different file, point `MEMORANDA_ENV` at it rather than editing code. The MemWal Python SDK expects `WALRUS_DELEGATE_KEY`, `WALRUS_ACCOUNT_ID`, and optionally `MEMWAL_ENV` (`prod` by default). Read the [official MemWal Python quick start](https://docs.wal.app/walrus-memory/python-sdk/quick-start) for account/key setup and environment requirements. Use a disposable demo account/namespace where possible.

The model client uses `DEEPSEEK_API_KEY`, with optional `DEEPSEEK_BASE_URL` and `DEEPSEEK_MODEL` overrides. Telegram is optional for web-only use; set `TELEGRAM_BOT_TOKEN` to enable it. `FIELDPACK_BASE` changes the bot's API base URL; `FIELDPACK_HOST` and `FIELDPACK_PORT` configure the notebook server (defaults: `127.0.0.1` and `8770`). `FIELDPACK_LAND_DEADLINE` and `FIELDPACK_ABANDON_COOLDOWN` optionally tune local outbox timing; leave their defaults unless you have reviewed the write-queue behavior.

Start the notebook:

```bash
.venv/bin/python server.py
```

Open `http://127.0.0.1:8770`. Choose **Create new**, save the generated passkey somewhere secure, and select language, currency, and timezone (the shop name is optional, and the header shows it once the book has one). A passkey is a bearer credential: anyone who has it can access that book.

For Telegram, start the bot in a second terminal after the notebook is running:

```bash
.venv/bin/python memoranda_bot.py
```

Open a direct chat with your configured bot, use `/key`, and send the book passkey as the next message. The bot also supports `/new`, `/book`, `/remind`, `/timezone`, `/release`, and `/help` (Indonesian aliases are available). Do not put the bot in a public group for a private book.

## Tests

Offline tests do not need a live Telegram bot or paid MemWal writes. Run the project suites with the same interpreter that has `memwal` installed (the store harness imports SDK types even when its relay client is faked):

```bash
.venv/bin/python -m py_compile server.py memoranda_bot.py packlib.py parse.py timezones.py
.venv/bin/python test_fieldpack.py
.venv/bin/python test_lang.py
.venv/bin/python test_timezones.py
.venv/bin/python test_channels.py
.venv/bin/python test_store.py
.venv/bin/python test_web_history.py
.venv/bin/python test_shop_name.py
.venv/bin/python test_outbox.py
```

The browser side has its own test. It loads the inline script out of `web/index.html` into a Node `vm` with the network stubbed, so it needs Node rather than the virtualenv:

```bash
node test_web_history.js
```

Two more suites drive the real inbound path and the real reminder pass without touching the Telegram wire — the send step is replaced by a recorder, but everything else is the live code, including the running notebook and the bindings file:

```bash
.venv/bin/python test_bot_live.py     # 34 checks on the inbound message path
.venv/bin/python test_alarm_live.py   # 14 checks on the reminder pass
```

`test_store.py` needs the interpreter that has `memwal` installed; the others run against the same one.

> **The two live suites are not offline.** They need the notebook server running with real
> MemWal credentials, and `test_alarm_live.py` performs **real MemWal writes** (the delivery
> is recorded in Walrus, so running it costs storage). Run them only when you intend those
> remote writes. `test_store.py` is the opposite: it drives a fake relay client, so it needs
> no network and no credentials.

`acceptance.py` is different: it sends real requests to a running server, creates a new book, and writes to the configured MemWal service. Run it only with a disposable test account and when you intend those remote writes:

```bash
# In terminal 1: start server.py
.venv/bin/python acceptance.py --url http://127.0.0.1:8770
```

Do not use the `--keep` option in a shared terminal or captured log: it prints a newly generated passkey. Historical evidence from a previous live acceptance run is summarized in [`docs/acceptance-notes.md`](docs/acceptance-notes.md); it is not a claim that the current revision has just passed that live scenario.

## Data and security model

The client sends a passkey to open a book; the local pack index stores only its hash. Web conversation text is separately saved in `data/web_history.json` for the latest 100 turns per book. It is local server data, not encrypted separately and not uploaded to Walrus.

- **Passkeys are bearer secrets.** The local pack index stores a hash, but the client needs the original key. Anyone with a key can read and write the associated book. There is no per-user access control, key rotation, revocation, or per-key rate limiting in this prototype.
- **The server operator is trusted.** MemWal provides encrypted storage, but this application's server holds the delegate credential needed to access the memory service. This is not a zero-knowledge design. Protect the server, `.env`, `data/`, and backups.
- **Local data is sensitive.** `data/` can contain pack metadata, local append-only journals, the bounded web conversation transcript, queued writes, Telegram bindings, delivery markers, and logs. Do not publish or upload it. The local journal/outbox can improve availability while a remote read/write is delayed, but it is not an encrypted backup and may expose customer information on the host.
- **Storage is append-only and remote availability/retention is external.** Corrections are represented as newer records, not edits. Walrus lease duration, rate limits, relayer behavior, and recovery semantics may change; do not treat this prototype as the authoritative accounting or backup system.
- **No public deployment is configured by this README.** The server defaults to loopback. If you deliberately expose it through a proxy/tunnel, add HTTPS, access controls, request limits, secure secret handling, monitoring, and a reviewed deployment configuration first.

## Current limitations

- The web chat transcript is stored in the application's local `data/web_history.json` file per verified book, limited to the latest 100 turns. It appears on another browser/device connected to the same server after that device opens the same book with its passkey. It is not stored in Walrus and will not follow if the app moves to another server without migrating that file. This transcript is web-only; Telegram messages are not imported because Telegram has its own chat history. Avoid putting credentials or passkeys in chat messages. The transcript is not encrypted separately from the server's local runtime data.

- This is a prototype; reconcile financial records against a proper accounting system.
- Supported handwritten UI/reply languages are Indonesian and English. Other languages may be selected, but parser behavior for them is unverified; cross-language matching of customer labels can be conservative.
- Currency settings cover current IDR/USD behavior; this is not a general multi-currency accounting engine.
- Reminder delivery requires the Telegram bot to be running, reachable, and bound to the correct book. Web-only mode stores and displays reminders but does not deliver Telegram messages.
- Telegram delivery uses local markers and an append-only "fired" record; network interruption or a process outage can delay delivery. Do not treat it as a guaranteed paging service.
- There is no self-service customer-name correction UI, encrypted export/import workflow, automated storage-lease renewal, or production-grade backup/restore flow.
- There is no production deployment manifest or automated CI workflow yet.

## Project layout

| File | Purpose |
|---|---|
| `server.py` | HTTP server, book/passkey handling, shared API, web transcript, write flusher |
| `memoranda_bot.py` | Telegram polling and scheduled reminder delivery |
| `channels/` | Channel interface and Telegram adapter |
| `brain.py` | Bot client for the notebook HTTP API |
| `parse.py` | Model-assisted extraction and deterministic proposal validation |
| `packlib.py` | MemWal records, local journal/outbox, fold, and derived ledger views |
| `timezones.py` | IANA timezone validation and reminder time calculations |
| `lang.py` | Language and currency behavior plus UI copy |
| `web/home.html` | English product landing page |
| `web/index.html` | Browser notebook |
| `requirements.txt` | Pinned Python runtime dependencies |
| `.env.example` | Names and placeholders for local configuration; contains no credentials |
| `LICENSE` | MIT license text |
| `test_*.py` | Offline and integration-oriented test suites |
| `test_web_history.js` | Node test for the browser notebook's transcript handling |
| `acceptance.py` | Live acceptance scenario; creates/writes a remote test book |
| `data/web_history.json` | Bounded, web-only conversation transcript keyed by book ID; sensitive runtime data, never publish |
| `data/` | Runtime state and personal data; never include in public screenshots or commits |

## License

MIT. See [`LICENSE`](LICENSE). You may use, modify, and redistribute this software, including commercially, as long as the copyright notice and this permission notice are kept. It is provided with no warranty.

## Verification

Checked on this revision:

- The shipped file list was reviewed against `.gitignore`. No book key, bot token, chat id, personal path, or reference to another project is committed; `.env`, `data/`, logs, and the one-off development scripts are excluded.
- Every documented offline suite passes: `py_compile`, `test_fieldpack`, `test_lang`, `test_timezones` (18/0), `test_channels`, `test_store` (30/30), `test_web_history.py`, `test_shop_name`, `test_outbox`, and the Node browser test.
- The two live suites pass against a running notebook with real credentials: `test_bot_live.py` (34/34) and `test_alarm_live.py` (14/14). They are kept out of the offline run because they write real MemWal blobs.
- The repository was proved to stand alone: the shipping files were extracted into an empty directory, a virtualenv was built from `requirements.txt` alone, and the server then created a book, recorded a note through the model, derived the customer balance (`owes 100`, `paid_total 50`), and answered a follow-up question from the stored record.

## Documentation

- [Screenshot checklist](docs/images/README.md)
- [Historical acceptance notes](docs/acceptance-notes.md)
- [Walrus blob-count evidence](docs/evidence/walrus-blob-count.txt)

## Source

- [Walrus Memory Python SDK Quick Start](https://docs.wal.app/walrus-memory/python-sdk/quick-start)
- [`memwal` on PyPI](https://pypi.org/project/memwal/)

## Credits

Built with Walrus Memory / MemWal, Python, Telegram, and an OpenAI-compatible language model API.

## Contributing

Open an issue before a major change. Keep user data and credentials out of pull requests. Add offline regression tests for behavior changes, and do not run `acceptance.py` against non-disposable accounts.

## Status

Prototype entry for Walrus Session 8. The notebook runs locally, and the public demo link is a Cloudflare quick tunnel that rotates on restart, so treat it as a demo rather than a hosted service.