"""The two doors the model is allowed to stand in, and nothing else.

It reads a messy sentence and it writes a sentence back. Everything between
those two points is arithmetic in packlib. The rule this file exists to enforce:

    the model proposes, the code decides.

One message is allowed to hold more than one fact, because people write more
than one fact in a message. "pak asep service 250rb dia baru bayar 100" is a job
and a payment, and losing the payment is how somebody ends up owing money they
already paid.

Its text is normalized, checked, and refused when it is not sure. It never sees
a balance, and it never writes a number that goes into one.
"""

import json
import os
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import httpx

import lang
import packlib
import timezones

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
TIMEOUT = 90


class ModelError(RuntimeError):
    pass


def _env(name, default=None):
    value = os.environ.get(name)
    return value if value else default


def call_model(messages, json_mode=True):
    base = _env("DEEPSEEK_BASE_URL", DEFAULT_BASE).rstrip("/")
    model = _env("DEEPSEEK_MODEL", DEFAULT_MODEL)
    key = _env("DEEPSEEK_API_KEY", "")
    if not key:
        raise ModelError("no DEEPSEEK_API_KEY in the environment")
    body = {"model": model, "messages": messages, "temperature": 0.2}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    last = None
    for _ in range(3):
        try:
            resp = httpx.post(base + "/chat/completions", json=body, timeout=TIMEOUT,
                              headers={"Authorization": "Bearer " + key})
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise ModelError("model unreachable: %s: %s" % (type(last).__name__, last))


# ---------------------------------------------------------------------------
# money, because this is the field that costs money when it is wrong
# ---------------------------------------------------------------------------

WORDS = {
    "nol": 0, "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6,
    "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10, "sebelas": 11,
}

SCALES = {"ribu": 1000, "juta": 1000000, "miliar": 1000000000}

DIGITS_RE = re.compile(r"(\d[\d.,]*)\s*(rb|ribu|k|jt|juta|m)?\b", re.I)

# What a unit suffix multiplies by. "m" is a million in both languages, which is
# the one place rupiah and dollars agree.
UNITS = {"rb": 1000, "ribu": 1000, "k": 1000, "jt": 1000000, "juta": 1000000,
         "m": 1000000}

# Scales people spell out. "150 thousand, paid" used to come back as "Did you
# mean 150 thousand or 150?", which is the book asking about the number the
# worker had just finished describing. Longest first so "million" is not read as
# a bare "m".
SPELLED_SCALES = (("billion", 1000000000), ("million", 1000000), ("thousand", 1000))

# A message that names its currency has answered the question by itself, so this
# beats the book setting: "$150" is dollars even inside an Indonesian book.
CURRENCY_MARKS = (
    ("USD", re.compile(r"\$|(?<![a-z])usd(?![a-z])|(?<![a-z])dollars?(?![a-z])"
                       r"|(?<![a-z])bucks?(?![a-z])", re.I)),
    ("IDR", re.compile(r"(?<![a-z])rp(?![a-z])|(?<![a-z])idr(?![a-z])"
                       r"|(?<![a-z])rupiah(?![a-z])", re.I)),
)


def marked_currency(text):
    """The currency a message names outright, when it names exactly one.

    Two currencies in one message means the message is not the place to decide,
    so it returns nothing and the book's own setting is used.
    """
    raw = str(text or "")
    found = [code for code, pattern in CURRENCY_MARKS if pattern.search(raw)]
    return found[0] if len(found) == 1 else None


def spelled_scale(text):
    for word, scale in SPELLED_SCALES:
        if word in str(text or "").lower():
            return scale
    return None


def _clean_number(raw, code="IDR"):
    """150.000 and 150,000 and 150000 all mean the same thing here.

    A decimal currency reads the separator the other way round. "$12.50" is
    twelve dollars fifty, and the rupiah rule would have made it 1250, which is
    off by a factor of a hundred and is exactly the kind of wrong this file
    exists to prevent. Three digits after the separator is still a thousands
    group, because that is the one shape that cannot be cents.
    """
    raw = raw.strip().rstrip(".,")
    if code != "IDR":
        parts = re.split(r"[.,]", raw)
        if len(parts) == 2 and 0 < len(parts[1]) <= 2:
            return _to_float(parts[0] + "." + parts[1])
        return _to_float("".join(parts))
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(",") == 1 and len(raw.split(",")[-1]) <= 2:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(".", "").replace(",", "")
    return _to_float(raw)


def _to_float(raw):
    try:
        return float(raw)
    except ValueError:
        return None


def _words_to_number(text):
    """seratus lima puluh ribu -> 150000.

    Spelled-out rupiah is how a lot of people actually type it, and getting this
    wrong is getting an amount wrong, so it is a small state machine over the
    words, tested against the shapes people use:

        seratus lima puluh ribu   150000
        lima belas ribu           15000
        dua juta                  2000000
        seribu                    1000
    """
    text = " ".join(str(text or "").lower().split())
    if not text:
        return None
    total, current, pending = 0, 0, 0
    seen = False
    for word in re.findall(r"[a-z]+", text):
        if word == "seratus":
            current += 100
            seen = True
        elif word == "seribu":
            total += (current + pending or 1) * 1000
            current = pending = 0
            seen = True
        elif word == "sejuta":
            total += (current + pending or 1) * 1000000
            current = pending = 0
            seen = True
        elif word in WORDS:
            pending = WORDS[word]
            seen = True
        elif word == "belas":
            current += 10 + pending
            pending = 0
        elif word == "puluh":
            current += (pending or 1) * 10
            pending = 0
        elif word == "ratus":
            current += (pending or 1) * 100
            pending = 0
        elif word in SCALES:
            total += (current + pending) * SCALES[word]
            current = pending = 0
    if not seen:
        return None
    return total + current + pending or None


def _read_amount(text, code=None, assumed_unit=None, answered=False):
    """(value or None, ambiguous, had_cents). One reader for every money field.

    Whether a bare number is ambiguous is a fact about the currency, not about
    the number. Rupiah speakers drop the "rb" all day: "service 150" means
    150 ribu, so a bare 150 is a real question. Dollar speakers do not: nobody
    writes $12.50 as "1250", so in a dollar book a bare 150 is 150 dollars and
    asking is just the book arguing with somebody who already told it.

    When the message names its currency, that beats the argument entirely, so a
    "$" in an Indonesian book still means dollars.

    answered is set when this number came back as the answer to that very
    question. The question offers both readings, so the second one has to be
    accepted: "150" answering "150 ribu atau 150?" used to get the same question
    again, which is a loop with no exit except typing "rb".
    """
    raw = str(text or "").strip()
    if not raw:
        return None, False, False
    code = marked_currency(raw) or code or lang.DEFAULT_CURRENCY
    digits = DIGITS_RE.search(raw)
    if digits:
        value = _clean_number(digits.group(1), code)
        if value is None:
            return None, True, False
        scale = UNITS.get((digits.group(2) or "").lower()) or spelled_scale(raw)
        if scale:
            return int(value * scale), False, False
        cents = code != "IDR" and value != int(value)
        if value < 5000 and code == "IDR":
            # Only rupiah gets the "did you mean thousands" question, and only
            # when this very message did not already show its scale.
            if assumed_unit:
                return int(value * assumed_unit), False, False
            if answered:
                return int(value), False, False
            return None, True, False
        return (int(value + 0.5) if code != "IDR" else int(value)), False, cents
    spelled = _words_to_number(raw)
    if spelled:
        return int(spelled), False, False
    return None, True, False


def amount_of(text, assumed_unit=None, currency=None):
    """Kept as a name because the tests use it. See _read_amount."""
    value, ambiguous, _cents = _read_amount(text, currency, assumed_unit)
    return value, ambiguous


def unit_in(text):
    """The thousands-or-millions scale a message is using, if it says so."""
    raw = str(text or "")
    match = DIGITS_RE.search(raw)
    if match:
        unit = (match.group(2) or "").lower()
        if UNITS.get(unit):
            return UNITS[unit]
    return spelled_scale(raw)


# ---------------------------------------------------------------------------
# the model's job: read the sentence
# ---------------------------------------------------------------------------

READ_PROMPT = """You read one message a small-business worker typed, in whatever
language they typed it, and return JSON only. You never guess a number: you copy
numbers exactly as written. You never translate a name, a street, or the thing
that was worked on: copy those exactly as written even when the message is in
another language, because that spelling is what the customer is stored under.

One message can contain more than one fact. Split them into "items".

Return exactly this shape:
{
  "intent": "log" | "ask" | "other",
  "person": string | null,        // the customer's name ONLY, e.g. "pak asep"
  "subject": string | null,       // the thing worked on, e.g. "AC ruang tamu"
  "subject_type": string | null,  // ac_unit | vehicle | room | garment | other
  "job_type": string | null,      // one of: servis | refill | ganti_oli | jahit | other
  "date_text": string | null,     // when the WORK happened, exactly as written
  "date_in_days": integer | null, // that same date counted in days from today:
                                  // "kemarin" -1, "yesterday" -1, "2 hari lalu" -2,
                                  // "today" 0, "tadi" 0. Null when the date is
                                  // absolute ("21 sep", "21/09").
  "followup_after_days": integer | null,  // optional interval explicitly requested
  // for offering again: "next 3 bulan" -> 90, "in 2 weeks" -> 14. Null unless asked.
  "items": [
    {"kind": "job",     "amount_text": string | null},
    {"kind": "payment", "amount_text": string | null, "when_text": string | null,
                        "when_in_days": integer | null},
    {"kind": "promise", "when_text": string | null, "when_in_days": integer | null,
                        "amount_text": string | null},
    {"kind": "task",    "what_text": string, "when_text": string | null,
                        "when_in_days": integer | null}
  ],
  "question": string | null       // only when intent is ask: the question verbatim
}

Meaning of the item kinds:
- "job": work that was done and may or may not be paid yet. One message is one
  job. Never split one job into two items because it describes two actions:
  "serviced the AC, refilled the freon" is one job, and "servis AC isi freon" is
  one job.
- "payment": money the customer actually handed over, now or before.
- "promise": money the customer said they will pay later. Only when the message
  is about paying. when_in_days is how many days from today that is: "minggu
  depan" 7, "next week" 7, "besok" 1, "tomorrow" 1, "in 2 weeks" 14, "bulan
  depan" 30. Fill it whenever the message gives a relative date, and fill
  when_text with the same words as written.
- "task": something the worker themselves asked to be reminded about that is not
  money, and not a payment. "2 minggu lagi minta isiin freon" is a task: what_text
  is what has to happen ("minta isiin freon", copied as written) and when_in_days
  14 is when to be reminded. A date that follows a task belongs to that task.

A date that comes after a job is only a promise when money is still owed. When
the message says the job is already paid, and the amount paid covers the job
("bayar cash", "paid cash", "lunas", "udah dibayar"), there is nothing left to
promise: any trailing phrase is a task, not a promise. Two facts from one message
never contradict each other.

The same words can belong to a task instead of a promise. Ask which fact the date
is attached to, in the sentence, by looking at which verb it sits next to.

A phrase like "next 3 bulan" or "next 3 months" after a job is NOT a promise. It
is how long until the job is worth offering again, so it belongs in
followup_after_days.

Rules: "belum lunas", "ngutang", "owes", "unpaid" mean the job is unpaid. "baru
bayar 100", "already paid 100" mean a payment of 100 happened. "nanti dibayar
minggu depan" or "the rest next week" is a promise for next week. Never invent a
name, a subject, or a number that is not in the message. Everything missing is
null. A promise item with no date and no amount is not a promise: leave it out."""


def read_message(text, playbook="ac_service", lang_code=None):
    """The proposal. The language is passed in so the reader knows the spelling
    it should expect, but the reader is not asked to translate anything: names
    and subjects stay as the worker typed them."""
    note = ""
    if lang_code and lang_code not in ("id",):
        note = "workers language: %s\n" % lang.prompt_name(lang_code)
    raw = call_model([
        {"role": "system", "content": READ_PROMPT},
        {"role": "user", "content": "%splaybook: %s\nmessage: %s"
         % (note, playbook, text)},
    ])
    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise ModelError("model did not return json: %s" % exc)
    data["_raw"] = text
    if not isinstance(data.get("items"), list):
        data["items"] = []
    return data


# ---------------------------------------------------------------------------
# the code's job: decide
# ---------------------------------------------------------------------------

HONORIFICS = frozenset((
    "pak", "bapak", "bu", "ibu", "mas", "mbak", "bang", "abang", "kak", "om",
    "tante", "sdr", "sdri", "mr", "mrs", "ms", "miss", "sir", "madam",
    "don", "sr", "sra", "mr", "hn", "hj",
))

RELATIVE = {
    "hari ini": 0, "tadi": 0, "today": 0, "barusan": 0,
    "kemarin": -1, "yesterday": -1,
    "besok": 1, "tomorrow": 1, "lusa": 2,
    "minggu depan": 7, "seminggu lagi": 7, "pekan depan": 7, "next week": 7,
    "bulan depan": 30, "sebulan lagi": 30, "next month": 30,
}


def explicit_clock(*texts):
    """Return an explicitly stated reminder time as (hour, minute), or None.

    The model's date fields used to retain only a day count; `lines_for()` then
    hard-coded every alarm to 09:00. Read the clock from the user's actual words
    so that an explicit time survives even if the model omits it from JSON.
    """
    daypart = {
        "am": "am", "a.m.": "am", "pm": "pm", "p.m.": "pm",
        "pagi": "pagi", "siang": "siang", "sore": "sore", "malam": "malam",
    }
    marked = re.compile(
        r"(?<![\w:])(?:(?:at|around|by|jam|pukul)\s*)?"
        r"(\d{1,2})(?::(\d{2}))?\s*"
        r"(a\.m\.|p\.m\.|am|pm|pagi|siang|sore|malam)\b", re.I)
    prefixed = re.compile(
        r"\b(?:at|around|by|jam|pukul)\s*(\d{1,2})(?::(\d{2}))?\b", re.I)
    for text in texts:
        raw = str(text or "")
        match = marked.search(raw)
        suffix = None
        if match:
            hour, minute = int(match.group(1)), int(match.group(2) or 0)
            suffix = daypart[match.group(3).lower()]
        else:
            match = prefixed.search(raw)
            if not match:
                continue
            hour, minute = int(match.group(1)), int(match.group(2) or 0)
        if minute > 59 or hour > 24 or (hour == 24 and minute != 0):
            continue
        if suffix in ("pm", "p.m."):
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + 12
        elif suffix in ("am", "a.m."):
            if not 1 <= hour <= 12:
                continue
            hour %= 12
        elif suffix == "malam":
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + 12
        elif suffix == "sore":
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + 12
        elif suffix == "siang":
            if not 1 <= hour <= 12:
                continue
            hour = 12 if hour == 12 else hour
        elif suffix == "pagi":
            if not 1 <= hour <= 12:
                continue
            hour %= 12
        elif hour == 24:
            hour = 0
        return hour, minute
    return None


def resolve_date(text, today=None):
    today = today or datetime.now()
    raw = str(text or "").strip().lower()
    if not raw:
        return today, False
    if raw in RELATIVE:
        return today + timedelta(days=RELATIVE[raw]), False
    months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6,
              "jul": 7, "agu": 8, "aug": 8, "ags": 8, "sep": 9, "okt": 10, "oct": 10,
              "nov": 11, "des": 12, "dec": 12}
    match = re.search(r"(\d{1,2})\s*[-/ ]\s*([a-z]{3,})", raw)
    if match:
        day, name = int(match.group(1)), match.group(2)[:3]
        if name in months:
            when = datetime(today.year, months[name], day)
            if when > today + timedelta(days=2):
                when = when.replace(year=today.year - 1)
            return when, False
    match = re.search(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", raw)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        try:
            when = datetime(today.year, month, day)
            if when > today + timedelta(days=2):
                when = when.replace(year=today.year - 1)
            return when, False
        except ValueError:
            return today, True
    match = re.search(r"(\d{1,3})\s*hari", raw)
    if match:
        return today + timedelta(days=int(match.group(1))), False
    match = re.search(r"(\d{1,2})\s*minggu", raw)
    if match:
        return today + timedelta(days=7 * int(match.group(1))), False
    match = re.search(r"(\d{1,2})\s*bulan", raw)
    if match:
        return today + timedelta(days=30 * int(match.group(1))), False
    return today, True


def _core_name(name):
    """The part of a name that is actually a name.

    "pak budi" and "budi" are the same person; "pak yudi" and "pak budi" are not.
    Comparing the full strings gets that second one wrong, because "pak_yudi" and
    "pak_budi" share six characters out of seven and the honorific is doing most
    of the matching. Comparing what is left after the honorific gives 4 out of 5
    against 3 out of 4, and the difference is the one that matters.
    """
    parts = [p for p in packlib.slug(name).split("_") if p and p not in HONORIFICS]
    return "".join(parts) if parts else packlib.slug(name).replace("_", "")


def _similar(new, known):
    """Names that could be the same person, with a score.

    The comparison runs on the core name when both sides have one, and on the
    whole string only when they do not. Running both and taking the best was the
    first attempt, and it let the honorific decide again: "pak_yudi" against
    "pak_budi" scores 6 of 7 characters, which is higher than the core comparison
    of "yudi" against "budi" is low. One comparison, the right one.
    """
    raw = packlib.slug(new).replace("_", "")
    core = _core_name(new)
    hits = []
    for who, person in known.items():
        for label in [person.get("name", ""), person.get("slug", "")] + person.get("aliases", []):
            if not label:
                continue
            label_core = _core_name(label)
            label_raw = packlib.slug(label).replace("_", "")
            if core and label_core:
                pairs = ((core, label_core),)
            else:
                pairs = ((raw, label_raw),)
            for mine, theirs in pairs:
                if not mine or not theirs:
                    continue
                if mine == theirs or mine in theirs or theirs in mine:
                    hits.append((who, 1.0))
                elif SequenceMatcher(None, mine, theirs).ratio() > 0.82:
                    hits.append((who, SequenceMatcher(None, mine, theirs).ratio()))
    hits.sort(key=lambda pair: -pair[1])
    return hits


def resolve_person(who_raw, people, lang_code=lang.DEFAULT_LANG):
    """(slug, needs_asking, question, display name).

    "Budi" and "Pak Budi" are the same person, so a single strong match is
    resolved rather than questioned. Only a genuine tie, or a weak match, is
    worth interrupting somebody about. When a person is resolved, the name that
    gets written back is the one already on file, never the raw sentence.
    """
    want = packlib.slug(who_raw)
    if not want:
        return None, True, lang.t(lang_code, "ask_person"), who_raw
    for who, person in people.items():
        labels = [person.get("name", ""), person.get("slug", "")] + person.get("aliases", [])
        if want in [packlib.slug(label) for label in labels if label]:
            return who, False, "", (person.get("name") or who)
    hits = {}
    for who, score in _similar(who_raw, people):
        hits[who] = max(hits.get(who, 0), score)
    if not hits:
        return want, False, "", who_raw
    best = max(hits.items(), key=lambda pair: pair[1])
    if len(hits) == 1 and best[1] >= 0.95:
        return best[0], False, "", (people[best[0]]["name"] or best[0])
    other = people[best[0]]["name"] or best[0]
    return None, True, lang.t(lang_code, "ask_person_clash", other), who_raw


def _days(value):
    """A day count from the model, or None. Strings are refused on purpose."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d{1,4}", value.strip()):
        return int(value.strip())
    return None


def plan(proposal, state, today=None, default_follow_up=None, lang_code=lang.DEFAULT_LANG,
         currency=None, timezone_name=None):
    """What the code intends to write, or why it refuses to write anything yet.

    Returns one of:
      {"action": "ask", "question": ...}
      {"action": "confirm", "field": ..., "question": ...}
      {"action": "commit", ..., "entries": [ ... ]}

    Nothing here consults the model, and the entries are built from normalized
    values only. A follow-up reminder is made only when the worker explicitly
    gives an interval. The product must not decide on its own when to contact a
    customer again.

    Dates arrive two ways and this prefers the number. when_in_days and
    date_in_days are day counts the model worked out, so "minggu depan", "next
    week" and "in 2 weeks" all land on the same code path and no language table
    has to be right about all of them.
    """
    timezone_name = timezones.resolve_timezone(
        timezone_name or state.get("timezone") or ((state.get("pack") or {}).get("tz"))
        or timezones.DEFAULT_TIMEZONE
    ) or timezones.DEFAULT_TIMEZONE
    today = today or timezones.local_now(timezone_name)
    intent = proposal.get("intent") or "other"
    if intent in ("ask", "other"):
        return {"action": "ask", "question": proposal.get("question") or proposal["_raw"]}

    who_raw = proposal.get("person")
    if not who_raw:
        return {"action": "confirm", "field": "person",
                "question": lang.t(lang_code, "ask_person_again")}

    person_slug, asking, question, display = resolve_person(
        who_raw, state.get("people", {}), lang_code)
    if asking:
        return {"action": "confirm", "field": "person", "question": question}
    person_slug = person_slug or packlib.slug(who_raw)

    items = [i for i in (proposal.get("items") or []) if isinstance(i, dict)]
    if not items:
        items = [{"kind": "job", "amount_text": proposal.get("amount_text")}]

    # One message is one job. The reader split "serviced the AC, refilled the
    # freon" into two job items on an English sentence, and the second one had
    # no number, so it would have written a second job worth nothing. Collapsing
    # is the fix. Two different job amounts, on the other hand, cannot be one
    # sentence with one customer in it, and silently keeping one of the two
    # numbers is exactly the bug class this file exists to prevent, so that gets
    # asked about instead.
    jobs = [i for i in items if (i.get("kind") or "job").lower() == "job"]
    job_amounts = []
    for item in jobs:
        raw = str(item.get("amount_text") or "").strip()
        if raw and raw not in job_amounts:
            job_amounts.append(raw)
    if len(job_amounts) > 1:
        return {"action": "confirm", "field": "amount",
                "question": lang.t(lang_code, "ask_two_amounts", " / ".join(job_amounts))}
    # The surviving items keep the order they were written in, because that order
    # is what the worker typed and the confirmation reads better for it. The
    # first job item survives, and it inherits the amount from whichever job item
    # carried one: on "serviced the AC, refilled freon 150rb" the reader put the
    # number on the second item, and keeping the empty first one would have
    # written a job worth nothing.
    kept, seen_job = [], False
    for item in items:
        if (item.get("kind") or "job").lower() == "job":
            if seen_job:
                continue
            if not str(item.get("amount_text") or "").strip() and job_amounts:
                item = dict(item, amount_text=job_amounts[0])
            seen_job = True
        kept.append(item)
    items = kept

    # One step of unit inference, said out loud in the confirmation, and only
    # when this very message shows its scale somewhere. Dollars skip it: a bare
    # dollar number is already the whole number, so borrowing the scale from a
    # sibling would turn "service 150k, paid 50" into a payment of 50,000.
    currency = currency or state.get("currency") or lang.currency_for(lang_code)
    scale = None
    if currency == "IDR":
        for item in items:
            scale = scale or unit_in(item.get("amount_text"))
        scale = scale or unit_in(proposal.get("date_text")) or None

    # A day count from the reader beats any word list: "next week" and "minggu
    # depan" both arrive as 7, so neither language needs a table entry to be
    # right. The words stay as the fallback for a proposal that has no count.
    job_days = _days(proposal.get("date_in_days"))
    if job_days is not None:
        job_when, job_fuzzy = today + timedelta(days=job_days), False
    else:
        job_when, job_fuzzy = resolve_date(proposal.get("date_text"), today)

    raw_interval = proposal.get("followup_after_days")
    # Reject booleans, floats, numeric strings, and non-positive intervals;
    # only a real positive integer extracted from the user's explicit wording
    # can create an offer-again reminder.
    interval = raw_interval if type(raw_interval) is int and raw_interval > 0 else None
    entries, assumed, rounded, mixed = [], [], [], []
    for index, item in enumerate(items):
        kind = (item.get("kind") or "job").lower()
        raw_amount = item.get("amount_text")
        if kind == "payment" and not str(raw_amount or "").strip():
            return {"action": "confirm", "field": "amount", "index": index,
                    "question": lang.t(lang_code, "ask_paid_amount")}
        if kind == "promise" and not str(raw_amount or "").strip() \
                and _days(item.get("when_in_days")) is None \
                and not str(item.get("when_text") or "").strip():
            continue    # a promise with no date and no amount is not a promise
        amount, ambiguous, cents = _read_amount(
            raw_amount, currency, scale if raw_amount else None,
            answered=bool(proposal.get("amount_answered")))
        if raw_amount and ambiguous:
            return {"action": "confirm", "field": "amount", "index": index,
                    "question": lang.t(lang_code, "ask_amount_bare",
                                       raw_amount, raw_amount, raw_amount)}
        if cents:
            # Cents cannot be held, so the amount was rounded and the
            # confirmation says so rather than quietly keeping the difference.
            rounded.append(str(raw_amount).strip())
        marked = marked_currency(str(raw_amount or ""))
        if marked and currency and marked != currency:
            # A dollar sign inside a rupiah book is read as written, and said out
            # loud. The ledger holds one number per entry and takes its unit from
            # the book, so quietly mixing the two is how a figure ends up meaning
            # something nobody typed.
            mixed.append(marked)
        if scale and raw_amount and re.fullmatch(r"\d+", str(raw_amount).strip()) \
                and int(raw_amount) < 5000:
            assumed.append(raw_amount)

        if kind == "payment":
            when = today
            days = _days(item.get("when_in_days"))
            if days is not None:
                when = today + timedelta(days=days)
            elif item.get("when_text"):
                when, _ = resolve_date(item["when_text"], today)
            entries.append({"kind": "pay", "amount": amount or 0, "when": when})
        elif kind == "promise":
            days = _days(item.get("when_in_days"))
            if days is not None:
                when = today + timedelta(days=days)
            else:
                when, fuzzy = resolve_date(item.get("when_text"), today)
                if fuzzy or when <= today:
                    when = today + timedelta(days=7)   # "nanti" with no date: a week
            entries.append({"kind": "promise", "amount": amount or 0, "when": when,
                            "timezone": timezone_name})
        elif kind == "task":
            what = str(item.get("what_text") or "").strip()
            if not what:
                continue    # a task with nothing to do is not a task
            days = _days(item.get("when_in_days"))
            if days is not None:
                when = today + timedelta(days=days)
            else:
                when, fuzzy = resolve_date(item.get("when_text"), today)
                if fuzzy or when <= today:
                    when = today + timedelta(days=7)
            entries.append({"kind": "task", "amount": 0, "when": when, "what": what,
                            "timezone": timezone_name})
        else:
            entries.append({"kind": "job", "amount": amount or 0, "when": job_when,
                            "job_type": proposal.get("job_type") or "other"})

    # A message cannot contradict itself. When the message states both the work
    # and what was paid for that work, and the payment already covers it, nothing
    # is left to promise: a "promise" there is the date having been glued to the
    # wrong fact. This is arithmetic, so it is decided here and not by the model.
    if any(e["kind"] == "job" for e in entries):
        owed = sum(e["amount"] for e in entries if e["kind"] == "job")
        paid = sum(e["amount"] for e in entries if e["kind"] == "pay")
        outstanding = max(0, owed - paid)
        kept = []
        for entry in entries:
            if entry["kind"] != "promise":
                kept.append(entry)
                continue
            if outstanding <= 0:
                # Paid in full, so this was a date glued to the wrong fact. The
                # worker still asked for something to happen on that day, so the
                # date is kept as a reminder instead of being thrown away. When
                # the reader did its job there is already a task holding it.
                if not any(e["kind"] == "task" for e in kept):
                    kept.append({"kind": "task", "amount": 0,
                                 "when": entry["when"], "what": "",
                                 "timezone": entry.get("timezone", timezone_name)})
                continue
            if entry["amount"] > outstanding:
                entry["amount"] = outstanding   # a promise cannot exceed the debt
            kept.append(entry)
        entries = kept

    if not entries:
        return {"action": "confirm", "field": "amount",
                "question": lang.t(lang_code, "ask_what")}
    # A reminder carries no money, so a message that is only a reminder is not a
    # message with a missing amount. Only a message made of money with no number
    # in it has to be asked about.
    money = [e for e in entries if e["kind"] in ("job", "pay", "promise")]
    if money and not any(e["kind"] == "job" for e in entries) \
            and money[0]["amount"] == 0:
        return {"action": "confirm", "field": "amount",
                "question": lang.t(lang_code, "ask_amount")}

    if interval is not None:
        for job in [e for e in entries if e["kind"] == "job"]:
            entries.append({"kind": "followup", "amount": 0,
                            "when": job["when"] + timedelta(days=interval),
                            "days": interval, "timezone": timezone_name})

    # Keep an explicit clock from the actual message. Date-only reminders retain
    # the established 09:00 default when converted to ledger lines.
    clock = explicit_clock(proposal.get("_raw"),
                           *(item.get("when_text") for item in items))
    if clock:
        for entry in entries:
            if entry["kind"] in ("promise", "task"):
                entry["when"] = entry["when"].replace(
                    hour=clock[0], minute=clock[1], second=0, microsecond=0)
                entry["explicit_time"] = True

    # slug("") returns a placeholder, so an empty subject has to be caught here
    # or every message without a unit mentioned grows a subject called "x".
    subject = packlib.slug(proposal.get("subject")) if proposal.get("subject") else ""
    known_person = person_slug in state.get("people", {})
    known_subject = subject in (state.get("people", {}).get(person_slug, {})
                                .get("subjects", {}))
    return {"action": "commit",
            "person": person_slug, "name": display or who_raw,
            "person_raw": packlib.slug(who_raw),
            "person_is_new": not known_person,
            "subject": subject,
            "subject_is_new": bool(subject) and not known_subject,
            "subject_label": proposal.get("subject"),
            "subject_type": proposal.get("subject_type"),
            "text": proposal["_raw"],
            "currency": currency,
            "assumed_thousands": sorted(set(assumed)),
            "rounded_cents": sorted(set(rounded)),
            "mixed_currency": sorted(set(mixed)),
            "entries": entries}


def _money(rupiah, lang_code=lang.DEFAULT_LANG, currency=None):
    """Kept as a name because the tests use it. The shape is per language now,
    the mark on the front is per book."""
    return lang.money(rupiah, lang_code, currency)


def lines_for(commit, lang_code=lang.DEFAULT_LANG):
    """Convert a normalized plan to ledger lines, retaining explicit clock time.

    A person line is only written when the person is new, or when a new spelling
    of their name shows up, which is recorded as an alias. Writing the raw
    sentence back as somebody's name is how a customer card ends up called
    "pak asep ngutang total biaya service 250rb".
    The body of a job line is the worker's own sentence, in their own language,
    on purpose: that is the record, and translating it would be inventing.
    """
    person = commit["person"]
    subject = commit.get("subject") or ""
    currency = commit.get("currency")
    first_when = commit["entries"][0]["when"]
    out = []
    raw_slug = commit.get("person_raw") or person
    if commit.get("person_is_new"):
        out.append(packlib.render("person", commit["name"], p=person,
                                  name=packlib.name_tag(commit["name"]),
                                  alias=raw_slug, at=first_when))
    elif raw_slug != person:
        out.append(packlib.render("person",
                                  lang.t(lang_code, "line_alias", commit["name"]),
                                  p=person, alias=raw_slug, at=first_when))
    if subject and commit.get("subject_is_new"):
        out.append(packlib.render("subject", commit.get("subject_label") or subject,
                                  p=person, s=subject,
                                  type=commit.get("subject_type") or "other",
                                  loc=packlib.slug(commit.get("subject_label") or ""),
                                  at=first_when))

    job_ids = []
    for entry in commit["entries"]:
        if entry["kind"] == "job":
            jid = packlib.job_id(person, subject, entry.get("job_type"), entry["when"],
                                 entry["amount"])
            job_ids.append(jid)
            out.append(packlib.render("job", commit["text"], p=person, s=subject,
                                      job=jid, type=entry.get("job_type") or "other",
                                      amount=entry["amount"], at=entry["when"]))
    for entry in commit["entries"]:
        if entry["kind"] == "pay":
            out.append(packlib.render("pay",
                                      lang.t(lang_code, "line_pay",
                                             _money(entry["amount"], lang_code,
                                                    currency)),
                                      p=person, ref=job_ids[-1] if job_ids else "",
                                      amount=entry["amount"], at=entry["when"]))
        elif entry["kind"] == "promise":
            fire = entry["when"] if entry.get("explicit_time") else \
                entry["when"].replace(hour=9, minute=0, second=0, microsecond=0)
            what = (lang.t(lang_code, "line_collect",
                           _money(entry["amount"], lang_code, currency))) \
                if entry["amount"] else lang.t(lang_code, "line_collect_left")
            out.append(packlib.render("rem", what, p=person, s=subject, kind="collect",
                                      fire=fire.strftime(packlib.STAMP),
                                      tz=entry.get("timezone") or timezones.DEFAULT_TIMEZONE,
                                      at=first_when))
        elif entry["kind"] == "task":
            fire = entry["when"] if entry.get("explicit_time") else \
                entry["when"].replace(hour=9, minute=0, second=0, microsecond=0)
            if entry.get("what"):
                what = lang.t(lang_code, "line_remind", entry["what"])
            else:
                what = lang.t(lang_code, "line_remind_generic", commit["name"])
            out.append(packlib.render("rem", what, p=person, s=subject, kind="task",
                                      fire=fire.strftime(packlib.STAMP),
                                      tz=entry.get("timezone") or timezones.DEFAULT_TIMEZONE,
                                      at=first_when))
        elif entry["kind"] == "followup":
            fire = entry["when"].replace(hour=9, minute=0, second=0, microsecond=0)
            out.append(packlib.render("rem", lang.t(lang_code, "line_offer_again",
                                                    commit.get("subject_label")
                                                    or "kerjaan"),
                                      p=person, s=subject, kind="follow_up",
                                      fire=fire.strftime(packlib.STAMP),
                                      tz=entry.get("timezone") or timezones.DEFAULT_TIMEZONE,
                                      at=first_when))
    return out


ANSWER_PROMPT = """You answer one question about a small business using ONLY the
JSON you are given. Rules:
- If the JSON does not contain the answer, say you do not have it recorded. Never
  estimate, never guess a number.
- Subject labels keep the spelling the worker typed, which may not be the
  language you are answering in. Match a question about a machine or a room to a
  subject by meaning, not by spelling.
- Amounts are in rupiah. Write them the way a speaker of the answer language
  writes them: %(money_hint)s
- Two sentences at most. No advice, no filler.
- Write your answer in %(language)s and in nothing else. Not one word of any
  other language, not even a greeting. Names of people and units are copied as
  they appear in the JSON."""


def answer(question, state, lang_code=lang.DEFAULT_LANG, lang_name=""):
    """The one place a model writes words somebody reads.

    So it is asked for a language and then checked, because asking is not a
    guarantee: measured on a locked pack, a plain prompt still came back in the
    wrong language often enough to matter. One retry, and the caller is told the
    result either way instead of shipping a sentence nobody can read.
    """
    spoken = lang.prompt_name(lang_code, lang_name)
    money_hint = {
        "id": "150000 is 150rb, 1500000 is 1,5jt",
        "en": "150000 is 150k, 1500000 is 1.5m",
    }.get(lang_code, "150000 is written with a thousands separator")
    system = ANSWER_PROMPT % {"language": spoken, "money_hint": money_hint}
    picture = json.dumps(packlib.summary(state), ensure_ascii=False)[:6000]
    turn = "data: %s\n\nquestion: %s" % (picture, question)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": turn}]
    said = str(call_model(messages, json_mode=False)).strip()
    ok, found, settled = lang.conforms(said, lang_code, lang_name)
    if ok:
        return said
    retry = messages + [
        {"role": "assistant", "content": said},
        {"role": "user", "content": "That answer was in %s. Answer again, in %s "
                                    "only." % (found or "another language", spoken)},
    ]
    again = str(call_model(retry, json_mode=False)).strip()
    ok2, _found2, _settled2 = lang.conforms(again, lang_code, lang_name)
    same = lang.slug_compare(again, said)
    if ok2 or not same:
        return again
    return said


def slug_compare(a, b):
    """Rough equality, for deciding whether a retry actually changed anything."""
    left = " ".join(str(a or "").lower().split())
    right = " ".join(str(b or "").lower().split())
    return left == right


def confirm_line(plan_item, lang_code=lang.DEFAULT_LANG):
    return plan_item.get("question") or lang.t(lang_code, "confirm_default")
