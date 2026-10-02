# Screenshot capture checklist

## Captured and reviewed

All five images below are in this directory. Each one was read back at full size
with OCR to confirm what it shows and that no key, token, or chat id is in frame.
Every name, amount, and date in them is a fictional demo record.

- `homepage.png` — the English landing page at `/`, including its prototype note for the session.
- `notebook-demo.jpg` — job notes, derived customer balances, and scheduled reminders for one demo shop.
- `cross-session-memory.png` — the same book opened on the web channel and asked about a settled customer recorded through the Telegram bot. The book key was hidden in the page before this capture.
- `reminder-notification.jpg` — the Telegram chat with the bot: the reminder list, the acknowledgement for a newly recorded job, and the reminder that arrived carrying the shop name. Only the bot name is in the header; no account name or number is visible.

Not captured, and not required: `create-book.png`. The creation form is reachable
from `/app` and adds little that `notebook-demo.jpg` does not already show.

A separate question-and-answer crop is deliberately not included: the cross-session
capture already contains the question, the answer, and the panels that show where the
answer came from, so a second crop of the same exchange would add nothing.

## Rules for any new capture

Before adding an image, inspect it at full resolution. Remove browser address-bar
query secrets, browser notifications, real names/phone numbers, book passkeys, API
keys, bot tokens, private Telegram chat IDs, and any contents from the live `data/`
directory. Do not use runtime screenshots or logs as assets.

Avoid screenshots of the health endpoint, logs, server console, environment files, or
real wallet/account dashboards. They do not explain the user flow and can leak
operational details.

## Browser test route

Use `/` for the landing page and `/app` for the notebook. A book setup screenshot should be staged with a fresh demo book. For reminder proof, capture the actual Telegram message sent by the configured bot, not a mock UI, and verify that its displayed time corresponds to the demo book's timezone.