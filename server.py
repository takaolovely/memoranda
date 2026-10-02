#!/usr/bin/env python3
"""Web prototype for the field pack: passkey in, chat, cards out.

One pack is one MemWal namespace. The passkey is a bearer token that resolves to
a pack, hashed at rest, compared in constant time. No wallet, no signup, no
account. Whoever holds the link holds the data, which is written down in the
README rather than hidden.

Run:  python3 server.py            (listens on 127.0.0.1:8770)
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
PACKS_PATH = os.path.join(DATA, "packs.json")
PENDING_PATH = os.path.join(DATA, "pending.json")
WEB_HISTORY_PATH = os.path.join(DATA, "web_history.json")
WEB_HISTORY_TURNS = 100
WEB_HISTORY_TEXT_LIMIT = 4000

# The project's own .env, and nothing else. An operator whose secrets live
# somewhere else points MEMORANDA_ENV at that file, rather than this code
# carrying a path from somebody's home directory.
ENV_FILES = tuple(p for p in (os.environ.get("MEMORANDA_ENV", "").strip(),
                              os.path.join(HERE, ".env")) if p)


def load_env():
    for path in ENV_FILES:
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not os.environ.get(key):
                os.environ[key] = value


load_env()

import lang  # noqa: E402
import packlib  # noqa: E402
import parse  # noqa: E402
import timezones  # noqa: E402

LOCK = threading.Lock()
PLAYBOOKS = {
    "ac_service": {"label": "Servis AC", "subject_types": ["ac_unit"],
                   "job_types": ["refill", "servis", "bongkar_pasang", "cuci"]},
    "workshop": {"label": "Bengkel", "subject_types": ["vehicle"],
                 "job_types": ["ganti_oli", "servis", "ganti_part"]},
    "tailor": {"label": "Jahit", "subject_types": ["garment"],
               "job_types": ["jahit", "permak"]},
    "generic": {"label": "Usaha lain", "subject_types": ["other"],
                "job_types": ["kerja", "other"]},
}


# ---------------------------------------------------------------------------
# packs and keys
# ---------------------------------------------------------------------------

def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def _write_json(path, blob):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(blob, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _valid_history_pack_id(pack_id):
    return bool(re.fullmatch(r"[0-9a-f]{8}", str(pack_id or "")))


def read_web_history(pack_id):
    """Return bounded browser transcript rows for a known book id."""
    if not _valid_history_pack_id(pack_id):
        return []
    with LOCK:
        all_history = _read_json(WEB_HISTORY_PATH, {})
        registered = {str(meta.get("pack_id")) for meta in _read_json(PACKS_PATH, {}).values()
                      if isinstance(meta, dict)}
        if pack_id not in registered:
            return []
        rows = all_history.get(pack_id, [])
        if not isinstance(rows, list):
            return []
        clean = []
        for row in rows[-WEB_HISTORY_TURNS * 2:]:
            if (not isinstance(row, dict) or row.get("role") not in ("me", "bot", "sys")
                    or not isinstance(row.get("text"), str)):
                continue
            clean.append({"role": row["role"], "text": row["text"][:WEB_HISTORY_TEXT_LIMIT],
                          "kind": "confirm" if row.get("kind") == "confirm" else ""})
        return clean


def append_web_turn(pack_id, user_text, assistant_text, passkey, assistant_kind=""):
    """Persist a completed web turn; replace accidental passkey echoes."""
    if not _valid_history_pack_id(pack_id):
        return False
    meta = pack_of(passkey)
    if not meta or str(meta.get("pack_id")) != pack_id:
        return False
    key = str(passkey or "").strip()
    clean = []
    for role, text, kind in (("me", user_text, ""), ("bot", assistant_text, assistant_kind)):
        value = str(text or "").strip()[:WEB_HISTORY_TEXT_LIMIT]
        if not value:
            continue
        if key and key in value:
            value = value.replace(key, "[redacted]")
        # The generated key is high-entropy; redact a pasted token-shaped value
        # as well, even if it belongs to another book.
        value = re.sub(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])",
                       "[redacted]", value)
        clean.append({"role": role, "text": value,
                      "kind": "confirm" if kind == "confirm" else ""})
    with LOCK:
        all_history = _read_json(WEB_HISTORY_PATH, {})
        rows = all_history.get(pack_id, [])
        if not isinstance(rows, list):
            rows = []
        all_history[pack_id] = (rows + clean)[-WEB_HISTORY_TURNS * 2:]
        _write_json(WEB_HISTORY_PATH, all_history)
    return True


def key_hash(passkey):
    return hashlib.sha256(("fieldpack|" + str(passkey)).encode("utf-8")).hexdigest()


def queued_total():
    """How many lines are waiting in the outboxes of packs that still exist.

    The flusher only walks the packs listed in packs.json, so an outbox left
    behind by a pack that has since been removed can never drain. Counting it
    would hold the health check permanently above zero, which makes a real
    backlog impossible to spot.
    """
    live = set()
    for meta in _read_json(PACKS_PATH, {}).values():
        namespace = (meta or {}).get("namespace")
        if namespace:
            live.add("%s.pending.jsonl" % namespace.replace(":", "_"))
    total = 0
    for name in os.listdir(DATA):
        if name not in live:
            continue
        try:
            with open(os.path.join(DATA, name), encoding="utf-8") as fh:
                total += sum(1 for line in fh if line.strip())
        except Exception:  # noqa: BLE001
            continue
    return total


def pack_of(passkey):
    packs = _read_json(PACKS_PATH, {})
    want = key_hash(passkey)
    for stored, meta in packs.items():
        if hmac.compare_digest(stored, want):
            return meta
    return None


def pack_lang(meta):
    """The language a pack speaks, from the pack itself rather than the browser.

    The line in Walrus is the authority: somebody opening the same key from a
    borrowed phone should get the language the owner chose, not the language of
    whatever device happens to be in their hand.
    """
    code = (meta or {}).get("lang")
    if code:
        return code, (meta.get("lang_name") or "")
    return lang.DEFAULT_LANG, ""


def pack_currency(meta, state=None):
    """The money a book is counted in, from the book itself.

    The line in Walrus wins, then the local note, then the market the language
    is read in. Language and money are separate settings on purpose: somebody who
    switches the page to English in Jakarta still gets paid in rupiah, and
    re-pricing a whole book because its labels changed would be a money bug and
    not a preference.
    """
    line = ((state or {}).get("pack") or {}).get("currency")
    return line or (meta or {}).get("cur") or lang.currency_for(pack_lang(meta)[0])


def create_pack(biz="ac_service", name="", lang_value="", currency="", timezone_value=""):
    code, lang_name = lang.resolve_lang(lang_value)
    cur = lang.resolve_currency(currency, code)
    tz = timezones.resolve_timezone(timezone_value) or timezones.DEFAULT_TIMEZONE
    passkey = secrets.token_urlsafe(18)
    pack_id = secrets.token_hex(4)
    namespace = packlib.namespace_for(pack_id)
    store = build_store(namespace)
    line = packlib.render("pack", lang.t(code, "line_pack", name or pack_id),
                          pk=pack_id,
                          biz=packlib.slug(PLAYBOOKS.get(biz, {}).get("label", "usaha")),
                          pb=biz, tz=tz, lang=code,
                          ln=packlib.slug(lang_name) if code == "xx" else "",
                          cur=cur, at=datetime.now())
    landed = store.write(line)
    packs = _read_json(PACKS_PATH, {})
    packs[key_hash(passkey)] = {"pack_id": pack_id, "namespace": namespace,
                                "biz": biz, "name": name, "lang": code,
                                "lang_name": lang_name, "cur": cur, "tz": tz,
                                "created": datetime.now().strftime(packlib.STAMP),
                                "landed": bool(landed)}
    _write_json(PACKS_PATH, packs)
    return {"passkey": passkey, "pack_id": pack_id, "landed": bool(landed),
            "lang": code, "lang_name": lang_name, "currency": cur,
            "timezone": tz, "timezone_label": timezones.zone_label(tz)}


def set_pack_settings(meta, lang_value="", currency="", timezone_value=""):
    """Change pack settings by writing another append-only Walrus line."""

    if lang_value:
        code, lang_name = lang.resolve_lang(lang_value)
    else:
        code, lang_name = (meta.get("lang") or lang.DEFAULT_LANG,
                           meta.get("lang_name") or "")
    cur = lang.resolve_currency(currency, code) if currency \
        else (meta.get("cur") or lang.currency_for(code))
    tz = timezones.resolve_timezone(timezone_value) if timezone_value else None
    if timezone_value and not tz:
        raise ValueError("unknown timezone")
    tz = tz or meta.get("tz") or timezones.DEFAULT_TIMEZONE
    store = build_store(meta["namespace"])
    line = packlib.render("pack", lang.t(code, "line_pack",
                                         meta.get("name") or meta["pack_id"]),
                          pk=meta["pack_id"],
                          biz=packlib.slug(PLAYBOOKS.get(meta.get("biz"), {})
                                           .get("label", "usaha")),
                          pb=meta.get("biz") or "ac_service", tz=tz,
                          lang=code, ln=packlib.slug(lang_name) if code == "xx" else "",
                          cur=cur, at=datetime.now())
    landed = store.write(line)
    packs = _read_json(PACKS_PATH, {})
    for stored, entry in packs.items():
        if entry.get("pack_id") == meta["pack_id"]:
            entry["lang"] = code
            entry["lang_name"] = lang_name
            entry["cur"] = cur
            entry["tz"] = tz
    _write_json(PACKS_PATH, packs)
    return {"ok": True, "lang": code, "lang_name": lang_name, "currency": cur,
            "timezone": tz, "timezone_label": timezones.zone_label(tz),
            "landed": bool(landed)}


def build_store(namespace):
    from memwal import MemWalSync
    client = MemWalSync.create(key=os.environ["WALRUS_DELEGATE_KEY"],
                               account_id=os.environ["WALRUS_ACCOUNT_ID"],
                               env=os.environ.get("MEMWAL_ENV", "prod"))
    # Without a logger every diagnostic in PackStore is swallowed, and the only
    # sign of trouble is a request that takes a minute. It took a whole session to
    # notice that.
    return packlib.PackStore(namespace, client, root=DATA,
                             log=lambda msg: print("store %s: %s" % (namespace, msg),
                                                   flush=True))


def reminder_view(state, code):
    """Reminders as the page shows them: decided from the state, dated in the
    pack's own language. The date is written here rather than in the page so a
    language we add tomorrow does not need the page edited.

    Every reader gets the same fields, which is why the distance ("in 90 days")
    and the job the reminder came out of are settled here too. The bot used to
    print a bare "26 Dec" and nothing else, and a date three months out with no
    distance on it reads as something that leaked in by accident.
    """
    out = []
    tz = (state.get("pack") or {}).get("tz") or timezones.DEFAULT_TIMEZONE
    today = timezones.local_now(tz)
    for rem in packlib.live_reminders(state):
        item = dict(rem)
        # The stored line carries the slug, because that is the key everything
        # else matches on. What a person reads is the display name, so it is
        # resolved here once for every reader. The panel used to show "tagih
        # sisa utang" with nobody attached to it, which is not a reminder.
        who = state["people"].get(item.get("person") or "") or {}
        item["slug"] = item.get("person") or ""
        if who.get("name"):
            item["person"] = who["name"]
        fire = packlib.stamp_of(rem.get("fire"))
        item["date"] = lang.short_date(fire, code) if fire else ""
        item["time"] = fire.strftime("%H:%M") if fire else ""
        item["days"] = (fire.date() - today.date()).days if fire else None
        item["when"] = _distance(item["days"], code)
        item["from"] = _came_from(state, item["slug"], item.get("subject"), code)
        out.append(item)
    # Nearest first. The line order is the order they were written in, which is
    # not the order anybody wants to read them in.
    out.sort(key=lambda r: r.get("fire") or "9999")
    return out


def _distance(days, code):
    """How far off a reminder is, in words. A past date says so."""
    if days is None:
        return ""
    if days < 0:
        return lang.t(code, "rem_late", -days)
    if days == 0:
        return lang.t(code, "rem_today")
    if days == 1:
        return lang.t(code, "rem_tomorrow")
    return lang.t(code, "rem_in_days", days)


def _came_from(state, slug, subject_slug, code):
    """Which job put this reminder in the book, so the line answers the question
    it raises. A follow-up reminder is born out of a finished job; without that
    date on screen it looks like a line nobody wrote.

    Read out of the jobs rather than out of the people view, because this runs
    against the folded state and the view is built later. The first version read
    a field the view adds and came back empty on every real pack while passing on
    a hand-built state, which is the sort of test that tests the test.
    """
    when = None
    for job in (state.get("jobs") or {}).values():
        if job.get("person") != slug or job.get("voided"):
            continue
        if subject_slug and job.get("subject") != subject_slug:
            continue
        stamp = packlib.stamp_of(job.get("when") or "")
        if stamp and (when is None or stamp > when):
            when = stamp
    if not when:
        return ""
    return lang.t(code, "rem_from", lang.short_date(when, code))


# ---------------------------------------------------------------------------
# pending confirmations, so one question gets one answer
# ---------------------------------------------------------------------------
def pending_set(pack_id, payload):
    with LOCK:
        allp = _read_json(PENDING_PATH, {})
        if payload is None:
            allp.pop(pack_id, None)
        else:
            allp[pack_id] = payload
        _write_json(PENDING_PATH, allp)


def pending_get(pack_id):
    with LOCK:
        return _read_json(PENDING_PATH, {}).get(pack_id)


# ---------------------------------------------------------------------------
# the turn
# ---------------------------------------------------------------------------

def commit(store, commit_plan, lang_code=lang.DEFAULT_LANG):
    """Write every line as one batch, and never hold the request on a refusal."""
    lines = parse.lines_for(commit_plan, lang_code)
    landed, waiting = store.write_many(lines)
    return landed, lines, waiting, store.queued()


def describe(commit_plan, lang_code=lang.DEFAULT_LANG, currency=None):
    """The confirmation the code writes, not the model. Deterministic on purpose.

    One message can carry a job and a payment, so this says both, and it says
    what the running balance is. That last part is the reason somebody types this
    sentence in the first place.

    Every word here comes from the language table, which is what makes the lock a
    fact rather than a hope: this is the text the worker actually reads, and no
    model touches it.
    """
    say_t = lambda key, *args: lang.t(lang_code, key, *args)
    jobs = [e for e in commit_plan["entries"] if e["kind"] == "job"]
    pays = [e for e in commit_plan["entries"] if e["kind"] == "pay"]
    promises = [e for e in commit_plan["entries"] if e["kind"] == "promise"]
    followups = [e for e in commit_plan["entries"] if e["kind"] == "followup"]
    label = (commit_plan.get("subject_label") or "kerjaan")
    job_sum = sum(e["amount"] for e in jobs)
    pay_sum = sum(e["amount"] for e in pays)

    say = say_t("recap_head", commit_plan["name"].title())
    if jobs:
        what = say_t("recap_job", label,
                     parse._money(job_sum, lang_code, currency)) if job_sum \
            else say_t("recap_job_no_amount", label)
        say += ", %s" % what
    if pays:
        say += ". %s" % say_t("recap_pay", parse._money(pay_sum, lang_code, currency))
        if jobs:
            left = job_sum - pay_sum
            if left > 0:
                say += ", %s" % say_t("recap_left",
                                      parse._money(left, lang_code, currency))
            elif left < 0:
                # Money handed over with no job behind it is money in hand, not a
                # debt with a minus sign in front of it. The confirmation used to
                # read "sisa utang -150rb", which is a sentence somebody has to
                # decode to find out they were paid.
                say += ", %s" % say_t("ui_credit",
                                      parse._money(-left, lang_code, currency))
            else:
                say += ", %s" % say_t("ui_settled")
    if promises:
        say += ". %s" % say_t("recap_promise",
                              lang.short_date(promises[0]["when"], lang_code))
    elif followups:
        say += ". %s" % say_t("recap_followup", followups[0]["days"],
                              lang.short_date(followups[0]["when"], lang_code))
    if commit_plan.get("assumed_thousands"):
        say += " %s" % say_t("recap_assumed",
                             ", ".join(commit_plan["assumed_thousands"]))
    if commit_plan.get("rounded_cents"):
        say += " %s" % say_t("recap_rounded",
                             ", ".join(commit_plan["rounded_cents"]))
    if commit_plan.get("mixed_currency"):
        say += " %s" % say_t("recap_mixed_currency",
                             ", ".join(lang.currency_name(c)
                                       for c in commit_plan["mixed_currency"]),
                             lang.currency_name(currency or ""))
    return say + "."


NOT_A_NAME = frozenset((
    # words that only show up when the reply is a sentence and not a name
    "utang", "hutang", "bayar", "berapa", "kapan", "apa", "siapa", "udah", "belum",
    "lunas", "sisa", "tagih", "kerjaan", "servis", "ac", "hari", "ini", "itu",
    "owe", "owes", "owed", "paid", "pay", "how", "much", "when", "what", "who",
    "unpaid", "still", "left", "total", "job", "the", "and", "for",
    "cuanto", "debe", "pago", "quanto", "quando", "deve",
))


def looks_like_name(reply):
    """Is this short reply a name, or a whole new sentence?

    "pak yudi" is a name. "pak yudi utang berapa?" is a question, and a question
    that arrives while the bot is waiting for a name is not an answer to that
    question: it is a new message. Without this check the whole question gets
    written down as the customer, which is how a card ends up called
    "Pak Yudi Utang Berapa?".
    """
    text = str(reply or "").strip()
    if not text or "?" in text or "!" in text:
        return False
    if any(ch.isdigit() for ch in text):
        return False
    words = text.strip(" .,").split()
    if not 1 <= len(words) <= 3:
        return False
    return not any(w.lower() in NOT_A_NAME for w in words)


def patch_proposal(proposal, field, reply, index=None, lang_code=lang.DEFAULT_LANG):
    """Apply a one-word answer to the thing that was asked about.

    A short answer fixes the field that was in doubt. Anything longer, or
    anything that is not shaped like the field it would fill, is treated as a
    fresh sentence, because that is what it is.

    index matters when a sentence carried two numbers: overwriting the first one
    because the second one was asked about is how a payment turns into a job.
    """
    reply = (reply or "").strip()
    if len(reply.split()) > 6:
        return None
    items = proposal.get("items") or []
    if field == "amount":
        # Whoever got here typed the amount as an answer, so the bare number they
        # sent is read literally from now on. The question offered both readings,
        # and asking again is a loop the worker cannot get out of by answering.
        proposal["amount_answered"] = True
        if index is not None and 0 <= index < len(items):
            items[index]["amount_text"] = reply
            return proposal
        for item in items:
            raw = item.get("amount_text")
            if raw and re.fullmatch(r"\d{1,4}", str(raw).strip()):
                item["amount_text"] = reply
                return proposal
        if not re.search(r"\d", reply):
            return None
        for item in items:          # nothing matched: fill the first hole
            if not str(item.get("amount_text") or "").strip():
                item["amount_text"] = reply
                return proposal
        proposal["amount_text"] = reply
        return proposal
    if field == "person":
        # "no, a new person" has to be recognised in the language the pack speaks,
        # or the answer becomes a customer literally named "new person".
        fresh = ("orang baru", "baru", "orang baru ya", "orang baru orang",
                 "new person", "a new person", "new", "unknown",
                 "persona nueva", "nueva persona", "nuevo", "nueva",
                 "pessoa nova", "nova pessoa", "nouveau", "nouvelle")
        if reply.lower().strip(" .!,") in fresh:
            return proposal
        if not looks_like_name(reply):
            return None
        proposal["person"] = reply
        return proposal
    proposal["_raw"] = "%s | %s" % (proposal.get("_raw", ""), reply)
    proposal["items"] = items + (parse.read_message(reply, "ac_service",
                                                    lang_code).get("items") or [])
    return proposal


def handle_turn(passkey, text):
    meta = pack_of(passkey)
    if not meta:
        return {"ok": False, "error": lang.t(lang.DEFAULT_LANG, "unknown_key")}
    code, lang_name = pack_lang(meta)
    store = build_store(meta["namespace"])
    state = store.state()
    timezone_name = ((state.get("pack") or {}).get("tz") or meta.get("tz")
                     or timezones.DEFAULT_TIMEZONE)
    state["timezone"] = timezone_name
    # The line in Walrus wins over the local note: the pack is the record, and a
    # pack written before languages existed simply reads as Indonesian.
    if (state.get("pack") or {}).get("lang"):
        code = state["pack"]["lang"]
        lang_name = (state["pack"].get("lang_name") or lang_name)
    biz = meta.get("biz") or "generic"

    pend = pending_get(meta["pack_id"])
    if pend:
        proposal = patch_proposal(dict(pend["proposal"]), pend.get("field"), text,
                                  pend.get("index"), code)
        pending_set(meta["pack_id"], None)
        if proposal is None:
            proposal = parse.read_message(text, biz, code)
    else:
        proposal = parse.read_message(text, biz, code)

    plan_item = parse.plan(proposal, state, lang_code=code,
                           currency=pack_currency(meta, state))
    out = finish(store, state, plan_item, meta, proposal, code, lang_name)
    out.setdefault("pack_id", meta["pack_id"])
    return out


def finish(store, state, plan_item, meta, proposal, lang_code=lang.DEFAULT_LANG,
           lang_name=""):
    if plan_item["action"] == "confirm":
        pending_set(meta["pack_id"], {"proposal": proposal,
                                      "field": plan_item.get("field"),
                                      "index": plan_item.get("index")})
        return {"ok": True, "kind": "confirm",
                "say": parse.confirm_line(plan_item, lang_code),
                "needs": plan_item.get("field"), "lang": lang_code}
    if plan_item["action"] == "ask":
        return {"ok": True, "kind": "answer", "lang": lang_code,
                "say": parse.answer(plan_item["question"], state, lang_code, lang_name)}
    if plan_item["action"] == "commit":
        landed, lines, waiting, queued = commit(store, plan_item, lang_code)
        # A refusal is not an error the person should have to act on. The lines
        # stay in the local outbox either way, and the flusher will retry them.
        say = describe(plan_item, lang_code, plan_item.get("currency"))
        fresh = store.state()
        return {"ok": True, "kind": "committed", "landed": bool(landed),
                "queued": queued, "say": say, "lines": len(lines),
                "lang": lang_code, "state": packlib.summary(fresh)}
    return {"ok": False, "error": lang.t(lang_code, "not_understood")}


# ---------------------------------------------------------------------------
# the background flusher: the outbox lands itself
# ---------------------------------------------------------------------------

def flusher(interval=30):
    """Keep trying whatever is queued, for every pack, in the background.

    Started as a thread at boot. It is why a rate limit cannot turn into a lost
    entry: the person is told the entry is queued, and this lands it later.
    """
    while True:
        time.sleep(interval)
        try:
            packs = _read_json(PACKS_PATH, {})
        except Exception:  # noqa: BLE001
            continue
        for meta in packs.values():
            try:
                store = build_store(meta["namespace"])
                if store.queued():
                    landed, waiting = store.flush(tries=1)
                    print("flusher: %s landed=%s waiting=%s left=%d"
                          % (meta["pack_id"], landed, waiting, store.queued()))
            except Exception as exc:  # noqa: BLE001
                print("flusher error on %s: %s: %s"
                      % (meta.get("pack_id"), type(exc).__name__, exc))


# ---------------------------------------------------------------------------
# http
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "fieldpack/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, payload, ctype="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _page(self, name):
        page = os.path.join(HERE, "web", name)
        if not os.path.exists(page):
            return self._send(404, {"error": "no page"})
        with open(page, "rb") as fh:
            return self._send(200, fh.read(), "text/html")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            return self._send(405, {"error": "method not allowed"})
        query = {}
        if "?" in self.path:
            for pair in self.path.split("?", 1)[1].split("&"):
                key, _, value = pair.partition("=")
                query[key] = value
        # "/" is the front page, "/app" is the notebook itself. Same file at
        # /index.html as before, so nothing that already pointed at it breaks.
        if path in ("/", "/home"):
            return self._page("home.html")
        if path in ("/app", "/index.html"):
            return self._page("index.html")
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if path == "/api/health":
            return self._send(200, {"ok": True, "packs": len(_read_json(PACKS_PATH, {})),
                                    "queued": queued_total()})
        if path == "/api/i18n":
            # The page carries no words of its own. Language choice is a URL
            # argument, so adding a language never means editing the HTML.
            code, _name = lang.resolve_lang(query.get("lang") or "")
            return self._send(200, lang.ui_bundle(code))
        if path == "/api/pack":
            meta = pack_of(query.get("passkey") or "")
            if not meta:
                return self._send(200, {"ok": False,
                                        "error": lang.t(lang.DEFAULT_LANG, "unknown_key")})
            store = build_store(meta["namespace"])
            state = store.state()
            code = (state.get("pack") or {}).get("lang") or meta.get("lang") \
                or lang.DEFAULT_LANG
            return self._send(200, {"ok": True, "pack_id": meta["pack_id"],
                                    "biz": meta["biz"], "lang": code,
                                    "currency": pack_currency(meta, state),
                                    "timezone": ((state.get("pack") or {}).get("tz")
                                                 or meta.get("tz")
                                                 or timezones.DEFAULT_TIMEZONE),
                                    "timezone_label": timezones.zone_label(
                                        (state.get("pack") or {}).get("tz")
                                        or meta.get("tz") or timezones.DEFAULT_TIMEZONE),
                                    "lang_name": (state.get("pack") or {}).get("lang_name")
                                    or meta.get("lang_name") or "",
                                    "state": packlib.summary(state),
                                    "queued": store.queued(),
                                    "waiting": store.retry_after(),
                                    "reminders": reminder_view(state, code)})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._body()

        if path == "/api/pack":
            action = body.get("action")
            if action == "create":
                out = create_pack(body.get("biz") or "ac_service", body.get("name") or "",
                                  body.get("lang") or "", body.get("cur") or "",
                                  body.get("tz") or "")
                return self._send(200, {"ok": True, **out})
            if action == "enter":
                meta = pack_of(body.get("passkey") or "")
                if not meta:
                    return self._send(200, {"ok": False,
                                            "error": lang.t(lang.resolve_lang(
                                                body.get("lang") or "")[0], "unknown_key")})
                store = build_store(meta["namespace"])
                state = store.state()
                code = (state.get("pack") or {}).get("lang") or meta.get("lang") \
                    or lang.DEFAULT_LANG
                return self._send(200, {"ok": True, "pack_id": meta["pack_id"],
                                        "biz": meta["biz"], "lang": code,
                                        "currency": pack_currency(meta, state),
                                        "timezone": ((state.get("pack") or {}).get("tz")
                                                     or meta.get("tz")
                                                     or timezones.DEFAULT_TIMEZONE),
                                        "lang_name": (state.get("pack") or {}).get("lang_name")
                                        or meta.get("lang_name") or "",
                                        "state": packlib.summary(state)})
            if action == "lang":
                meta = pack_of(body.get("passkey") or "")
                if not meta:
                    return self._send(200, {"ok": False, "error": "unknown key"})
                try:
                    out = set_pack_settings(meta, body.get("lang") or "",
                                            body.get("cur") or "",
                                            body.get("tz") or "")
                except Exception as exc:  # noqa: BLE001
                    return self._send(200, {"ok": False, "error": "%s: %s"
                                            % (type(exc).__name__, exc)})
                return self._send(200, out)

        if path in ("/api/turn", "/api/web/turn"):
            try:
                passkey = body.get("passkey") or ""
                text = body.get("text") or ""
                out = handle_turn(passkey, text)
                if path == "/api/web/turn" and out.get("ok"):
                    try:
                        meta = pack_of(passkey)
                        if meta:
                            append_web_turn(meta["pack_id"], text, out.get("say", ""), passkey,
                                            "confirm" if out.get("kind") == "confirm" else "")
                    except Exception as history_error:  # noqa: BLE001
                        # Do not report a committed ledger turn as failed because
                        # transcript storage had a transient local I/O problem.
                        print("web history write failed: %s: %s" %
                              (type(history_error).__name__, history_error), flush=True)
            except Exception as exc:  # noqa: BLE001
                out = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            return self._send(200, out)

        if path == "/api/state":
            meta = pack_of(body.get("passkey") or "")
            if not meta:
                return self._send(200, {"ok": False,
                                        "error": lang.t(lang.DEFAULT_LANG, "unknown_key")})
            store = build_store(meta["namespace"])
            state = store.state()
            code = (state.get("pack") or {}).get("lang") or meta.get("lang") \
                or lang.DEFAULT_LANG
            return self._send(200, {"ok": True, "pack_id": meta["pack_id"],
                                    "history": read_web_history(meta["pack_id"]),
                                    "state": packlib.summary(state),
                                    "lang": code,
                                    "currency": pack_currency(meta, state),
                                    "timezone": ((state.get("pack") or {}).get("tz")
                                                 or meta.get("tz")
                                                 or timezones.DEFAULT_TIMEZONE),
                                    "lang_name": (state.get("pack") or {}).get("lang_name")
                                    or meta.get("lang_name") or "",
                                    "queued": store.queued(),
                                    "waiting": store.retry_after(),
                                    "reminders": reminder_view(state, code)})

        if path == "/api/fired":
            # A reminder that has been delivered writes itself down as delivered.
            # Which reminders are *worth* delivering is decided by
            # packlib.live_reminders on every read, so this only records that the
            # message went out. The ref is the reminder's fire stamp, which is the
            # only handle a reminder carries today.
            meta = pack_of(body.get("passkey") or "")
            if not meta:
                return self._send(200, {"ok": False,
                                        "error": lang.t(lang.DEFAULT_LANG, "unknown_key")})
            ref = (body.get("ref") or "").strip()
            if not ref:
                return self._send(200, {"ok": False, "error": "ref kosong"})
            store = build_store(meta["namespace"])
            line = packlib.render("fired", body.get("text") or "delivered", ref=ref)
            landed = store.write(line)
            return self._send(200, {"ok": True, "ref": ref, "landed": bool(landed),
                                    "queued": store.queued()})

        return self._send(404, {"error": "not found"})


def main():
    port = int(os.environ.get("FIELDPACK_PORT", "8770"))
    host = os.environ.get("FIELDPACK_HOST", "127.0.0.1")
    threading.Thread(target=flusher, daemon=True).start()
    server = ThreadingHTTPServer((host, port), Handler)
    print("fieldpack prototype on http://%s:%d" % (host, port))
    print("packs file: %s" % PACKS_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
