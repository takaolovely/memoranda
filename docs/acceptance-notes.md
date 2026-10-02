# Acceptance-test evidence (historical)

The original acceptance run was recorded on 25 September 2026 against a live prototype and a newly created Walrus Memory book. It is preserved here as historical evidence, not as a claim that the current revision has just passed the live acceptance scenario. The separately recorded historical reminder/timezone confirmation should not be treated as part of this acceptance run.

The original transcript and generated pack identifier were kept under the runtime `data/` directory and are intentionally not part of the public repository. Use a disposable book when running `acceptance.py`; it creates a book and writes records to the configured remote memory service. For current test commands and product behavior, see the root [README](../README.md).

## What that run covered

- A bare amount in an IDR book triggered a clarification instead of being guessed.
- The clarified amount was recorded and contributed to the customer balance.
- A natural-language query returned the recorded balance and latest service date.
- Repeating the same job did not double the balance.
- A payment reduced the balance to zero.
- A fresh read retained the expected balance.
- A follow-up reminder record was present in the book.

The historical test output reported **12/12 checks passed**. Its exact transcript contained a generated book identifier and dated customer examples, so it is not reproduced here. Reminder delivery was not covered by that acceptance run; reminder scheduler behavior is covered separately by offline channel/timezone tests, and actual Telegram delivery requires a running, correctly bound bot.

## Re-run carefully

See the README's **Tests** section. `acceptance.py` makes remote writes and prints a new passkey in its normal output; do not run it against a production account or retain its output in a public terminal/log.

Historical test counts and timing are tied to that recorded run. They are not current benchmark guarantees and should not be used as claims about a different revision or deployment.

## Screenshot checklist

Use a dedicated fictional demo book. Capture the English homepage, book setup with no visible passkey, a notebook with fictional jobs/balances, and a Telegram reminder request plus delivered reminder with timezone visible. Inspect every screenshot before publication for passkeys, bot tokens, chat identifiers, phone numbers, real customer information, and browser notifications. Never copy screenshots or logs from `data/` into the public repository.

## Security note

The prototype server keeps sensitive runtime files under `data/`, including journals, queues, pack metadata, Telegram bindings, logs, and reminder delivery markers. Keep that directory excluded from version control and treat it as private runtime data.