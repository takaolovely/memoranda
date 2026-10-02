"""Lines, tags, and the fold: the part of this that is arithmetic, not guesswork.

A pack is one MemWal namespace. One line is one fact. Nothing is ever edited;
a correction is another line. State is whatever falls out of reading every line
in order, which is why the answer to "how much does Budi owe" never comes from a
model.

Two things here were measured the hard way on an earlier bot using the same
memory, and both cost real bugs to find:

  * timestamps carry microseconds. Two lines written in the same turn that share
    a stamp leave the winner to whatever order recall happens to return, and one
    of those orders loses a line silently.
  * a read that should match but comes back empty is retried on a growing delay,
    because a namespace with memories was measured returning nothing at the two
    second mark and everything at the five second mark.
"""

import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime

import timezones

# Tags the code understands. A tag outside this set is inert, so a model that
# invents one cannot corrupt anything.
TAGS = (
    "k",       # kind: pack | person | subject | job | pay | void | rem | fired
    "pk",      # pack id
    "biz",     # business kind, free short slug: ac | bengkel | jahit
    "pb",      # playbook id
    "tz",      # timezone of the pack
    "lang",    # language the pack speaks: id | en | xx
    "ln",      # that language's own name when it is not one we have words for
    "cur",     # money the pack is read in: IDR | USD | any code it names
    "p",       # person slug
    "name",    # display name, underscores for spaces
    "alias",   # another way the same person gets written
    "phone",
    "s",       # subject slug
    "type",    # subject type, or job type
    "loc",     # where the subject is
    "job",     # job id
    "amount",  # integer rupiah
    "at",      # when it happened, YYYY-MM-DDTHH:MM:SS
    "ref",     # what this line points at
    "fire",    # when a reminder should speak
    "kind",    # reminder kind: follow_up | collect | task
    "renewed", # this line was re-written to extend its lease
    "ver",     # snapshot version
)

KINDS = ("pack", "person", "subject", "job", "pay", "void", "rem", "fired")

STAMP = "%Y-%m-%dT%H:%M:%S"
STAMP_US = "%Y-%m-%dT%H:%M:%S.%f"
DAY = "%Y-%m-%d"

_TAG_RE = re.compile(r"#([a-z]+):([^\s#]+)")

BAIT = (
    "customer service job payment money owe debt repair unit machine room "
    "reminder follow up collect invoice amount date person address phone "
    "ac freon oli servis jahit kos hutang bayar pelanggan"
)
RECALL_LIMIT = 300
MAX_DISTANCE = 0.95
NAMESPACE_PREFIX = "fieldpack:"

READ_AGAIN_AFTER = (0.6, 2.0, 3.0, 4.0)
SETTLE_SECONDS = 240
BACKOFF_SECONDS = 45

# How long a write may hold an HTTP request. Measured writes take twenty to
# forty seconds and under rate limiting they can take longer than any deadline a
# person would sit through, so the request is not where the waiting belongs: the
# line is recorded locally, the reply goes out, and the background flusher lands
# it. Ten seconds is enough to catch a fast write and short enough that nobody
# watches a spinner.
LAND_DEADLINE = float(os.environ.get("FIELDPACK_LAND_DEADLINE", "10"))

# After a request gives up on a write, the attempt is still running in its own
# thread and it clears the outbox itself if it succeeds. Sending the same batch
# again during that window would buy a second copy of the same lines, so the
# outbox stays shut for a minute.
ABANDON_COOLDOWN = int(os.environ.get("FIELDPACK_ABANDON_COOLDOWN", "60"))


def now_stamp():
    return datetime.now().strftime(STAMP_US)


def slug(text, limit=32):
    """A stable handle for a name. Spaces become underscores so the tag parses."""
    keep = [c.lower() if c.isalnum() else "_" for c in str(text or "")]
    out = re.sub(r"_+", "_", "".join(keep)).strip("_")
    return (out or "x")[:limit]


def name_tag(text, limit=40):
    """A name as a person reads it, with underscores standing in for the spaces
    a tag cannot carry.

    `slug()` is for matching: it lowercases and that is right for a key. Using
    it for the name meant "Mr. John" was stored as `mr_john` and read back as
    "mr john", and no amount of work at the reading end can put back what was
    thrown away at the writing end. The key stays the slug; what a person reads
    keeps the case it was typed in.
    """
    out = re.sub(r"[#\s]+", "_", str(text or "").strip())
    out = re.sub(r"_+", "_", out).strip("_")
    return out[:limit]


def render(line_kind, text, **tags):
    """One line: what a person would read, then the tags the code reads."""
    if line_kind == "pack" and tags.get("tz"):
        text = "%s timezone=%s" % (text or "", tags["tz"])
    parts = []
    for name in TAGS:
        if name in tags and tags[name] not in (None, ""):
            value = tags[name]
            if isinstance(value, datetime):
                value = value.strftime(STAMP)
            parts.append("#%s:%s" % (name, value))
    return "%s #k:%s %s" % ((text or "").strip().rstrip("."), line_kind,
                            " ".join(p for p in parts if p != "#k:%s" % line_kind))


def tags_of(line):
    found = {}
    for name, value in _TAG_RE.findall(line or ""):
        if name not in TAGS:
            continue
        if found.get(name):
            found[name] = found[name] + "," + value
        else:
            found[name] = value
    return found


def body_of(line):
    return _TAG_RE.sub("", line or "").strip()


def kind_of(line):
    return tags_of(line).get("k", "")


def stamp_of(raw):
    """Read a stamp written on a line back into a datetime."""
    for fmt in (STAMP_US, STAMP, "%Y-%m-%dT%H:%M", DAY):
        try:
            return datetime.strptime(raw or "", fmt)
        except ValueError:
            continue
    return None


def when_of(line):
    return stamp_of(tags_of(line).get("at", ""))


def job_id(person, subject, job_type, when, amount):
    """Content addressed, so sending the same sentence twice is one job."""
    raw = "|".join([str(person), str(subject), str(job_type),
                    when.strftime(DAY) if hasattr(when, "strftime") else str(when),
                    str(amount)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# the fold
# ---------------------------------------------------------------------------

def fold(lines):
    """Turn lines into what the bot knows. Pure: same lines, same answer."""
    state = {"pack": {"tz": timezones.DEFAULT_TIMEZONE}, "people": {}, "jobs": {}, "payments": [], "reminders": [],
             "currency": ""}
    ordered = []
    for line in lines:
        when = when_of(line)
        ordered.append((when or datetime.min, line))
    ordered.sort(key=lambda pair: pair[0])

    for when, line in ordered:
        tag = tags_of(line)
        kind = tag.get("k")
        text = body_of(line)

        if kind == "pack":
            body_tz = re.search(r"\btimezone=([A-Za-z0-9_+./-]+)", text)
            saved_tz = tag.get("tz") or (body_tz.group(1) if body_tz else "")
            # The shop name is in the readable half of the line ("pack Berry
            # Repair timezone=..."), not in a tag, so it is read back the way a
            # person reads it. A pack created without a name is written with its
            # pack id in that slot, and a hex id is not a shop name.
            body_name = re.match(r"\s*pack\s+(.*?)\s+timezone=", text or "")
            # A #name: tag is written in slug form, the same way a person line
            # is, so it is put back the way it was typed.
            tagged_name = (tag.get("name") or "").replace("_", " ").strip()
            saved_name = tagged_name or (body_name.group(1) if body_name else "").strip()
            if not saved_name or saved_name == (tag.get("pk") or ""):
                saved_name = ""
            state["pack"] = {"id": tag.get("pk"), "biz": tag.get("biz"),
                             "playbook": tag.get("pb"), "name": saved_name,
                             "tz": timezones.resolve_timezone(saved_tz)
                             or timezones.DEFAULT_TIMEZONE,
                             "lang": tag.get("lang") or "id",
                             "lang_name": (tag.get("ln") or "").replace("_", " "),
                             "currency": tag.get("cur") or ""}
            state["currency"] = state["pack"]["currency"]

        elif kind == "person":
            who = tag.get("p")
            if not who:
                continue
            person = state["people"].setdefault(
                who, {"slug": who, "name": "", "aliases": [], "phone": "",
                      "subjects": {}, "balance": 0, "paid": 0, "owed": 0})
            if tag.get("name"):
                person["name"] = tag["name"].replace("_", " ")
            for alias in (tag.get("alias") or "").split(","):
                if alias and alias not in person["aliases"]:
                    person["aliases"].append(alias)

        elif kind == "subject":
            who, sub = tag.get("p"), tag.get("s")
            if not who or not sub:
                continue
            person = state["people"].setdefault(
                who, {"slug": who, "name": "", "aliases": [], "phone": "",
                      "subjects": {}, "balance": 0, "paid": 0, "owed": 0})
            person["subjects"][sub] = {
                "slug": sub,
                "type": tag.get("type", ""),
                "loc": (tag.get("loc") or "").replace("_", " "),
                "label": text or sub.replace("_", " "),
            }

        elif kind == "job":
            jid = tag.get("job")
            if not jid:
                continue
            amount = int(tag.get("amount") or 0)
            state["jobs"][jid] = {
                "id": jid, "person": tag.get("p"), "subject": tag.get("s"),
                "type": tag.get("type", ""), "amount": amount,
                "when": (when.strftime(DAY) if when else ""),
                "text": text, "voided": False,
            }

        elif kind == "pay":
            amount = int(tag.get("amount") or 0)
            state["payments"].append({"person": tag.get("p"), "ref": tag.get("ref", ""),
                                      "amount": amount,
                                      "when": (when.strftime(DAY) if when else "")})

        elif kind == "void":
            target = tag.get("ref")
            if target in state["jobs"]:
                state["jobs"][target]["voided"] = True

        elif kind == "rem":
            state["reminders"].append({"person": tag.get("p"), "subject": tag.get("s"),
                                       "kind": tag.get("kind", "follow_up"),
                                       "fire": tag.get("fire", ""),
                                       "timezone": (timezones.resolve_timezone(tag.get("tz"))
                                                    or state["pack"].get("tz")
                                                    or timezones.DEFAULT_TIMEZONE),
                                       "text": text, "spoken": False})

        elif kind == "fired":
            target = tag.get("ref")
            for rem in state["reminders"]:
                if rem["fire"] == target or rem.get("id") == target:
                    rem["spoken"] = True
            # Aware reminder stamps and their stable sent marker are UTC strings.
            # Match equivalent instants rather than relying on differing offsets.
            try:
                fired_at = datetime.fromisoformat(str(target))
            except (TypeError, ValueError):
                fired_at = None
            if fired_at and fired_at.tzinfo is not None:
                fired_utc = fired_at.astimezone(timezones.ZoneInfo("UTC"))
                for rem in state["reminders"]:
                    try:
                        stamp = datetime.fromisoformat(str(rem.get("fire") or ""))
                    except (TypeError, ValueError):
                        continue
                    if stamp.tzinfo is not None and stamp.astimezone(timezones.ZoneInfo("UTC")) == fired_utc:
                        rem["spoken"] = True

    for job in state["jobs"].values():
        person = state["people"].get(job["person"])
        if person and not job["voided"]:
            person["owed"] += job["amount"]
    for pay in state["payments"]:
        person = state["people"].get(pay["person"])
        if person:
            person["paid"] += pay["amount"]
    for person in state["people"].values():
        person["balance"] = person["owed"] - person["paid"]
    return state


def summary(state, limit=12):
    """A small, exact picture of the pack, for the model to talk about only.

    Payments belong in here. Asking "how much has he paid" and getting "I do not
    have that recorded" is the right answer for a summary that only carries what
    is owed, and it is a bad answer for the person asking: the number was in the
    pack the whole time. That refusal showed up in five languages at once, which
    is how it was found.
    """
    people = []
    for person in sorted(state["people"].values(), key=lambda p: -p["balance"]):
        jobs = [j for j in state["jobs"].values()
                if j["person"] == person["slug"] and not j["voided"]]
        jobs.sort(key=lambda j: j["when"], reverse=True)
        pays = [p for p in state["payments"] if p["person"] == person["slug"]]
        pays.sort(key=lambda p: p["when"], reverse=True)
        people.append({
            "name": person["name"] or person["slug"],
            # Paid more than the jobs came to is not a debt with a minus sign in
            # front of it, it is money the worker is holding. Saying "owes -50k"
            # gets answered as "he owes minus fifty" by anything reading it.
            "owes": max(person["balance"], 0),
            "credit": max(-person["balance"], 0),
            "balance": person["balance"],
            "paid_total": person["paid"],
            "paid_recently": [{"when": p["when"], "amount": p["amount"]}
                              for p in pays[:5]],
            "subjects": [{"label": s["label"], "type": s["type"],
                          "last_job": next((j["when"] for j in jobs
                                            if j["subject"] == s["slug"]), "")}
                         for s in person["subjects"].values()],
            "last_jobs": [{"what": j["type"], "when": j["when"],
                           "amount": j["amount"]} for j in jobs[:5]],
        })
    return {"pack": state["pack"], "people": people[:limit]}


def live_reminders(state, limit=20):
    """The reminders worth showing, decided from the state and not from the line.

    A collect reminder for somebody who owes nothing is not worth showing. The
    balance moved after that line was written, and a line written to Walrus stays
    written, so the only place this can be decided is here. Doing it here means a
    line that was wrong the day it landed stops being wrong the moment the
    balance says so, without anybody having to edit anything.

    Offer-again reminders are never hidden this way: the worker explicitly
    chose when to follow up, independent of the outstanding balance.
    """
    out = []
    for rem in state["reminders"]:
        if rem.get("kind") == "collect":
            person = state["people"].get(rem.get("person") or "")
            if person is None or person["balance"] <= 0:
                continue
        out.append(rem)
    return out[-limit:]


# ---------------------------------------------------------------------------
# reading and writing one namespace
# ---------------------------------------------------------------------------
class PackStore:
    """One namespace, with the settle window covered locally.

    `client` is injected so the folded logic can be tested with no network.
    """

    def __init__(self, namespace, client, root=None, log=None):
        self.namespace = namespace
        self.client = client
        self.root = root or os.path.join(os.path.expanduser("~"), "fieldpack", "data")
        self.log = log or (lambda msg: None)
        os.makedirs(self.root, exist_ok=True)
        self.pending_path = os.path.join(
            self.root, "%s.pending.jsonl" % namespace.replace(":", "_"))
        self.journal_path = os.path.join(
            self.root, "%s.journal.jsonl" % namespace.replace(":", "_"))

    # ---- the local copy, which is also the backup file --------------------

    def journal(self):
        """Every line this machine has written to this pack, in order.

        This exists because of what Walrus is not. Reading a pack back is a
        similarity search, not a file listing, so completeness is never
        guaranteed by the read itself. `restore()` was measured returning two
        memories out of five in this account, so it is not a backup path either.
        A plain append-only file on this machine is boring, and it is the only
        thing here that can be read exactly.
        """
        if not os.path.exists(self.journal_path):
            return []
        out = []
        with open(self.journal_path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    text = json.loads(raw).get("text") or ""
                except Exception:  # noqa: BLE001
                    continue
                if text:
                    out.append(text)
        return out

    def _append_journal(self, lines):
        if not lines:
            return
        with open(self.journal_path, "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps({"text": line, "at": now_stamp()},
                                    ensure_ascii=False) + "\n")

    # ---- pending writes, so an accepted line is never lost ----------------

    def pending(self):
        if not os.path.exists(self.pending_path):
            return []
        rows = []
        with open(self.pending_path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rows.append(json.loads(raw))
                except Exception:  # noqa: BLE001
                    continue
        return rows

    def _save_pending(self, rows):
        if not rows:
            if os.path.exists(self.pending_path):
                os.remove(self.pending_path)
            return
        tmp = self.pending_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, self.pending_path)

    # ---- reading ----------------------------------------------------------

    def lines(self, query=None, limit=None, expect=0, patient=True):
        """Every line Walrus will hand back, retried while it settles.

        `expect` is how many lines the local copy knows about, and `patient` says
        whether it is worth waiting for the count to arrive. It is worth it only
        on first contact, when the local copy is empty and Walrus is the only
        source. After that the local copy is the faster truth, and waiting out an
        index that is a few seconds behind buys nothing except a slower answer:
        five retries with sleeps is almost ten seconds on every reply.

        Past the recall limit Walrus cannot return them all, so waiting would be
        pointless and it does not.
        """
        ceiling = min(expect, limit or RECALL_LIMIT) if patient else 0
        # Initialised before the loop on purpose. Every attempt below can fail and
        # continue, and when they all fail this is the only thing left to return.
        # Without it, a relay that refuses every read raised UnboundLocalError out
        # of the read path, and the whole turn answered with that instead of with
        # the local copy it already had.
        out = []
        for wait in (0.0,) + READ_AGAIN_AFTER:
            if wait:
                time.sleep(wait)
            try:
                res = self.client.recall(query or BAIT, limit=limit or RECALL_LIMIT,
                                         namespace=self.namespace,
                                         max_distance=MAX_DISTANCE)
            except Exception as exc:  # noqa: BLE001
                self.log("recall failed: %s: %s" % (type(exc).__name__, exc))
                continue
            out, seen = [], set()
            for item in (res.results or []):
                text = (getattr(item, "text", "") or "").strip()
                key = " ".join(text.split())
                if key and key not in seen:
                    seen.add(key)
                    out.append(text)
            if out and len(out) >= ceiling:
                return out
            if out and patient:
                self.log("recall returned %d line(s), the local copy has %d"
                         % (len(out), expect))
        return out

    def state(self):
        """Walrus lines plus the local copy plus whatever is still in the outbox.

        Three sources, because each one covers a failure the others do not:

          * Walrus is the record, and it is what survives this machine.
          * the local copy covers a read that has not caught up yet, and a recall
            that is a similarity search rather than a listing, which means the
            pack can be complete on chain and still fail to come back in one go.
          * the outbox covers a write the relayer has accepted but not landed.

        A line that has been accepted but has not landed yet is still a fact the
        person just told us, and the reply has to reflect it. Reading the outbox
        into the fold is what makes "saldo jadi 150rb" true the moment they say
        it, instead of half a minute later.

        A read also teaches the local copy: whatever Walrus has and this machine
        has not seen gets written down, so a second device that opens the same key
        ends up with a full replica instead of a half-read one.
        """
        known = {" ".join(l.split()) for l in self.journal()}
        mined = self.lines(expect=len(known), patient=not known)
        fresh = [t for t in mined if " ".join(t.split()) not in known]
        if fresh:
            self.log("walrus had %d line(s) the local copy did not" % len(fresh))
            self._append_journal(fresh)
        lines, seen = [], set()
        for text in list(mined) + self.journal() \
                + [r.get("text") or "" for r in self.pending()]:
            key = " ".join(str(text).split())
            if key and key not in seen:
                seen.add(key)
                lines.append(key)
        return fold(lines)

    # ---- writing ----------------------------------------------------------

    def write_many(self, lines, tries=2):
        """Queue every line, then try once to land the whole batch.

        The relayer answers a refused write with 429 and a retry_after, and the
        account limit is measured per hour. So a write is not allowed to hold the
        request: the lines go into the outbox, one attempt is made, and whatever
        does not land stays queued for the background flusher. Six lines that
        each retried four times took eighteen minutes before this.
        """
        rows = self.pending()
        for line in lines:
            rows.append({"text": line, "at": now_stamp()})
        self._save_pending(rows)
        # The local copy is written as soon as the line is accepted, before the
        # relayer has had a say. Whatever happens to the write, this machine can
        # still read back what the person said.
        self._append_journal(lines)
        return self.flush(tries=tries)

    def write(self, line):
        return self.write_many([line])[0]

    def retry_after(self):
        """Seconds still left on the hold, or 0 if the outbox is open.

        The file holds the moment the hold ends, not how long it lasts. A length
        would be read the same way forever, because nothing rewrites that file
        once it is written, and the outbox would then stay shut for good. An
        outbox that never reopens is where entries go to be forgotten.

        A number small enough to be an old-format leftover is treated as long
        expired, so the packs that were already stuck open themselves.
        """
        path = self.pending_path + ".retry"
        if not os.path.exists(path):
            return 0
        try:
            with open(path, encoding="utf-8") as fh:
                until = float(fh.read().strip() or 0)
        except Exception:  # noqa: BLE001
            return 0
        return max(0, int(round(until - time.time())))

    def _set_retry_after(self, seconds):
        path = self.pending_path + ".retry"
        if seconds:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("%.0f" % (time.time() + float(seconds)))
        elif os.path.exists(path):
            os.remove(path)

    def flush(self, tries=2, respect_retry_after=True, deadline=None):
        """Try to land the outbox. Returns (landed, waiting_seconds).

        The attempt runs in its own thread with a deadline, because a person
        typing a job should not sit through a slow relayer. Whatever is still in
        flight when the deadline passes stays in the outbox and lands itself
        later; the request is answered with "queued" instead of hanging.
        """
        deadline = LAND_DEADLINE if deadline is None else deadline
        rows = self.pending()
        if not rows:
            self._set_retry_after(0)
            return True, 0
        if respect_retry_after:
            wait = self.retry_after()
            if wait > 0:
                self.log("holding the outbox: the relayer asked for %ss" % wait)
                return False, wait
        left = list(rows)
        waiting = 0
        for attempt in range(tries):
            if not left:
                break
            outcome = {}

            def land(batch=left):
                try:
                    from memwal import RememberBulkItem
                    self.client.remember_bulk_and_wait(
                        [RememberBulkItem(text=r["text"], namespace=self.namespace)
                         for r in batch])
                    outcome["ok"] = True
                    # Only the rows that were actually sent leave the outbox.
                    # Emptying the whole file was wrong: an abandoned attempt that
                    # lands late would take newer rows with it, and those rows had
                    # never been sent anywhere.
                    sent = {" ".join(str(r.get("text") or "").split()) for r in batch}
                    left_over = [r for r in self.pending()
                                 if " ".join(str(r.get("text") or "").split()) not in sent]
                    self._save_pending(left_over)
                    if not left_over:
                        self._set_retry_after(0)
                except Exception as exc:  # noqa: BLE001
                    outcome["err"] = exc

            worker = threading.Thread(target=land, daemon=True)
            worker.start()
            worker.join(deadline)
            if worker.is_alive():
                # The attempt is still in the air. Holding the request open would
                # not make it land any sooner, so the outbox is shut for a minute
                # instead: the abandoned attempt clears it itself if it succeeds,
                # and if it does not, the flusher picks the batch up after the
                # cooldown without a second copy being sent in the meantime.
                self._set_retry_after(ABANDON_COOLDOWN)
                self.log("still writing after %ss, leaving %d line(s) queued, "
                         "outbox shut for %ss" % (deadline, len(left),
                                                  ABANDON_COOLDOWN))
                return False, 0
            if outcome.get("ok"):
                left = []
                break
            exc = outcome.get("err")
            waiting = _retry_after_from(exc) or waiting
            self.log("write refused (%s: %s), attempt %d"
                     % (type(exc).__name__, exc, attempt + 1))
            if waiting:
                self._set_retry_after(waiting)
                break
            if attempt < tries - 1:
                time.sleep(BACKOFF_SECONDS)
        self._save_pending(left)
        return (not left), waiting

    def queued(self):
        return len(self.pending())


def namespace_for(pack_id):
    clean = "".join(c for c in str(pack_id or "") if c.isalnum() or c in "-_")
    return NAMESPACE_PREFIX + (clean or "anon")


def _retry_after_from(exc):
    """How long a 429 asked us to wait, read out of the error body.

    The relayer answers a refused write with a JSON body carrying
    retry_after_seconds. Waiting the time it asked for beats guessing, and it
    beats hammering it and staying refused.
    """
    text = str(exc)
    match = re.search(r'"retry_after_seconds"\s*:\s*(\d+)', text)
    if match:
        return int(match.group(1))
    match = re.search(r"retry.after[^0-9]{0,12}(\d+)", text, re.I)
    return int(match.group(1)) if match else 0
