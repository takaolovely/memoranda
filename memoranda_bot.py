"""Memoranda on Telegram.

One process, two loops. The inbound loop takes what a person typed and hands it
to the notebook; the reminder loop wakes up on a timer, asks the notebook which
reminders are due, and pushes them. They are threads in the same process because
they share one binding table and neither is heavy enough to be worth a queue.

The reminder loop is the part that did not exist before. Until now a reminder was
a line in a book that somebody had to open. A reminder that only appears when you
look is not an alarm, it is a list.

Run:
    .venv/bin/python memoranda_bot.py

Needs the notebook server running (server.py, port 8770). It is a client of the
notebook over HTTP, never a second copy of it.
"""

import os
import pathlib
import re
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lang  # noqa: E402
import commands as cmd  # noqa: E402
import timezones  # noqa: E402
from brain import Brain, BrainError  # noqa: E402
from channels.base import BindingStore  # noqa: E402
from channels.telegram import Telegram, TelegramError  # noqa: E402

ENV_PATH = os.path.join(HERE, ".env")
REMINDER_EVERY = 45          # seconds between passes
PER_CHAT_PER_PASS = 3        # so binding an old book does not dump twenty messages
IGNORE_OLDER_THAN = timedelta(days=30)
FIRE_GRACE = timedelta(seconds=5)
# How old a message may be at startup and still be handled. See
# pending_at_start for why there is a line here at all.
STALE_AFTER = timedelta(minutes=10)
# The shape of a passkey, used to recognise one pasted on its own.
KEY_MIN, KEY_MAX = 16, 48
LOG_PATH = os.path.join(HERE, "data", "bot.log")


class Tee:
    """Print to the screen and to a file at the same time.

    Never raises. A dead pipe on the screen side must not be able to stop the
    bot: the file is the copy that matters.
    """

    def __init__(self, path, stream):
        self.stream = stream
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.file = open(path, "a", encoding="utf-8", buffering=1)
        except OSError:
            self.file = None

    def write(self, text):
        # The file first. If the screen pipe is full and nobody is reading it,
        # writing there blocks, and anything queued behind it is lost. The file
        # is the copy that has to survive.
        if self.file:
            try:
                self.file.write(text)
            except Exception:  # noqa: BLE001
                pass
        try:
            self.stream.write(text)
        except Exception:  # noqa: BLE001
            pass

    def flush(self):
        for target in (self.file, self.stream):
            try:
                target.flush()
            except Exception:  # noqa: BLE001
                pass


def looks_like_key(text):
    """Is this one word that could be a book key, with no command in front?

    People tap /key in the Telegram menu and then send the key as a second
    message. Nothing about that is wrong, and the bot asking them to try again
    is the bot being pedantic about its own syntax. A key has no spaces, is long
    and is made of key characters. A note about a customer is not.
    """
    word = (text or "").strip()
    if word.startswith("/") or not KEY_MIN <= len(word) <= KEY_MAX:
        return False
    return all(char.isalnum() or char in "-_" for char in word)


def load_env():
    """Read the .env next to this file. Never printed, never logged."""
    if not os.path.exists(ENV_PATH):
        raise SystemExit("no .env at %s" % ENV_PATH)
    for raw in pathlib.Path(ENV_PATH).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def pack_lang_for(binding, tg_payload):
    """The pack's language wins; before binding, guess from Telegram's locale."""
    if binding and binding.get("lang"):
        return binding["lang"]
    code = ((tg_payload.get("from") or {}).get("language_code") or "").lower()
    if code.startswith("id") or code.startswith("in"):
        return "id"
    return "en"


def money(value, code):
    return lang.money(value or 0, code)


class Bot:
    def __init__(self, token, base, bindings=None, sent_path=None):
        self.tg = Telegram(token)
        self.brain = Brain(base)
        # Injectable so the routing and de-duplication logic can be tested with
        # no network and no writes to the real files.
        self.bindings = bindings or BindingStore()
        self.sent_path = sent_path or os.path.join(HERE, "data", "reminders_sent.json")
        self.sent_lock = threading.Lock()
        self.stop = threading.Event()

    # ---- remembering what was already delivered --------------------------

    def _sent(self):
        import json
        if not os.path.exists(self.sent_path):
            return {}
        try:
            with open(self.sent_path, encoding="utf-8") as fh:
                rows = json.load(fh)
            return rows if isinstance(rows, dict) else {}
        except (ValueError, OSError):
            return {}

    def _mark_sent(self, external_id, ref):
        """Kept on disk as well as in Walrus.

        The Walrus write can be queued behind a rate limit for a minute. Without
        a local note, the next pass would see the reminder as unspoken and send it
        again, and the person would get the same message twice while the system
        was behaving exactly as designed.
        """
        import json
        with self.sent_lock:
            rows = self._sent()
            rows.setdefault(external_id, [])
            if ref not in rows[external_id]:
                rows[external_id].append(ref)
            rows[external_id] = rows[external_id][-200:]
            tmp = self.sent_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False)
            os.replace(tmp, self.sent_path)

    def _already_sent(self, external_id, ref):
        rows = self._sent().get(external_id) or []
        if ref in rows:
            return True
        # Some releases stored the exact legacy fire string; compare its parsed
        # wall-clock form too, so fractional seconds / ISO formatting remain safe.
        try:
            target = datetime.fromisoformat(str(ref)).replace(tzinfo=None)
        except ValueError:
            return False
        for old in rows:
            try:
                if datetime.fromisoformat(str(old)).replace(tzinfo=None) == target:
                    return True
            except ValueError:
                continue
        return False

    # ---- commands --------------------------------------------------------

    def say(self, external_id, text):
        try:
            self.tg.send(external_id, text)
            return True
        except TelegramError as exc:
            print("[send] %s" % exc, flush=True)
            return False

    def cmd_help(self, ext, code):
        """Assembled from commands.py, so it cannot describe a command that is
        not there. The names come from that table; only the descriptions come
        from the language table."""
        lines = [lang.bot_string(code, "help_head"), ""]
        for name, action in cmd.help_rows():
            hint = " <key>" if action in cmd.TAKES_ARGUMENT else ""
            lines.append("%s%s - %s" % (name, hint, lang.bot_string(code, "cmd_" + action)))
        lines.append("")
        lines.append(lang.bot_string(code, "help_tail"))
        self.say(ext, "\n".join(lines))

    def ask_for_book(self, ext, code):
        """Said whenever something needs a book and this chat has none."""
        self.say(ext, lang.bot_string(code, "unbound",
                                      cmd.shown("new"), cmd.shown("key")))

    def cmd_new(self, ext, payload, code):
        self.tg.notify_looking(ext)
        try:
            made = self.brain.create_pack(biz="ac_service", name="",
                                          lang=code)
        except BrainError:
            self.say(ext, lang.bot_string(code, "down"))
            return
        key = made.get("passkey") or ""
        self.bindings.bind(ext, key, made.get("pack_id") or "", made.get("lang") or code)
        print("[new] %s -> buku %s" % (ext, (made.get("pack_id") or "?")[:8]), flush=True)
        self.say(ext, lang.bot_string(code, "new_ok", key))

    def cmd_key(self, ext, arg, code):
        key = (arg or "").strip()
        if not key:
            self.say(ext, lang.bot_string(code, "need_key"))
            return
        try:
            entered = self.brain.enter(key)
        except BrainError:
            self.say(ext, lang.bot_string(code, "down"))
            return
        if not entered.get("ok"):
            print("[key] %s -> kunci tidak ketemu" % ext, flush=True)
            self.say(ext, lang.bot_string(code, "bad_key", cmd.shown("new")))
            return
        self.bindings.bind(ext, key, entered.get("pack_id") or "",
                           entered.get("lang") or code)
        print("[key] %s -> nyambung ke buku %s" % (ext, (entered.get("pack_id") or "?")[:8]),
              flush=True)
        self.say(ext, lang.bot_string(code, "bound"))

    def cmd_release(self, ext, code):
        self.bindings.unbind(ext)
        print("[release] %s dilepas" % ext, flush=True)
        self.say(ext, lang.bot_string(code, "released", cmd.shown("key")))

    def cmd_book(self, ext, binding, code):
        self.show_book(ext, binding, code, reminders_only=False)

    def cmd_remind(self, ext, binding, code):
        self.show_book(ext, binding, code, reminders_only=True)

    def cmd_timezone(self, ext, binding, arg, code):
        requested = (arg or "").strip()
        if not requested:
            try:
                out = self.brain.state(binding["passkey"])
            except BrainError:
                self.say(ext, lang.bot_string(code, "down"))
                return
            tz = out.get("timezone") or timezones.DEFAULT_TIMEZONE
            self.say(ext, lang.bot_string(code, "tz_current", tz,
                                          timezones.zone_label(tz)))
            return
        resolved = timezones.resolve_timezone(requested)
        if not resolved:
            examples = ", ".join("%s (%s)" % row for row in timezones.choices()[:6])
            self.say(ext, lang.bot_string(code, "tz_invalid", examples))
            return
        try:
            saved = self.brain.settings(binding["passkey"], tz=resolved)
        except BrainError:
            self.say(ext, lang.bot_string(code, "down"))
            return
        if not saved.get("ok"):
            self.say(ext, lang.bot_string(code, "down"))
            return
        self.say(ext, lang.bot_string(code, "tz_saved", resolved,
                                      timezones.zone_label(resolved)))

    def show_book(self, ext, binding, code, reminders_only=False):
        try:
            out = self.brain.state(binding["passkey"])
        except BrainError:
            self.say(ext, lang.bot_string(code, "down"))
            return
        if not out.get("ok"):
            self.say(ext, lang.bot_string(code, "bad_key"))
            return
        shop = (((out.get("state") or {}).get("pack") or {}).get("name") or "").strip()
        lines = []
        if shop:
            # Which shop this is, in the channel that has no header to read it
            # from. One key can be pasted into more than one chat, so a /book or
            # /remind reply names the book it actually read.
            lines.append(lang.bot_string(code, "shop_head", shop))
            lines.append("")
        if not reminders_only:
            people = (out.get("state") or {}).get("people") or []
            head = lang.bot_string(code, "book_head")
            lines.append(head)
            if not people:
                lines.append(lang.bot_string(code, "empty"))
            for person in people:
                bits = []
                if person.get("owes"):
                    bits.append("%s %s" % (lang.bot_string(code, "owed"),
                                           money(person["owes"], code)))
                if person.get("credit"):
                    bits.append("%s %s" % (lang.bot_string(code, "credit"),
                                           money(person["credit"], code)))
                if person.get("paid_total"):
                    bits.append("%s %s" % (lang.bot_string(code, "paid"),
                                           money(person["paid_total"], code)))
                lines.append("")
                lines.append("%s: %s" % (person.get("name"), ", ".join(bits) or "-"))
                for subject in person.get("subjects") or []:
                    lines.append("  %s" % subject.get("label"))
            lines.append("")
        rems = out.get("reminders") or []
        lines.append(lang.bot_string(code, "debt_head"))
        if not rems:
            lines.append(lang.bot_string(code, "no_rem"))
        for rem in rems:
            # Date, distance, and where it came from. "/book" used to print a
            # bare "26 Dec" next to a follow-up nobody remembered asking for,
            # which reads like a stray line rather than an alarm three months
            # out that the book set for itself.
            bits = [b for b in (rem.get("date"), rem.get("time"),
                                rem.get("when"), rem.get("from")) if b]
            lines.append("- %s: %s (%s)" % (rem.get("person") or "?",
                                            rem.get("text") or "",
                                            ", ".join(bits)))
        if not reminders_only:
            lines.append("")
            lines.append(lang.bot_string(code, "followup_manual"))
        self.say(ext, "\n".join(lines))

    # ---- inbound ---------------------------------------------------------

    def handle_message(self, payload):
        ext = self.tg.external_id(payload)
        text = self.tg.text_of(payload)
        binding = self.bindings.get(ext)
        code = pack_lang_for(binding, payload)
        if not text:
            return
        # One lookup, no chain of string comparisons. The names live in
        # commands.py and this does not care what they are.
        word, _, _rest = text.partition(" ")
        action = cmd.resolve(word) if cmd.is_command(text) else None
        # One line per message, so "did my message even arrive" is a question the
        # log answers. The text itself is not written down: it is somebody's
        # business, and the log is a file on a machine.
        print("[in] %s %s" % (ext, action or "teks %d huruf" % len(text)), flush=True)

        if action in ("start", "help"):
            self.cmd_help(ext, code)
            return
        if action == "new":
            self.cmd_new(ext, payload, code)
            return
        if action == "key":
            self.cmd_key(ext, cmd.argument_of(text), code)
            return
        if action == "timezone":
            if not binding:
                self.ask_for_book(ext, code)
                return
            self.cmd_timezone(ext, binding, cmd.argument_of(text), code)
            return
        if action == "release":
            self.cmd_release(ext, code)
            return
        if action in ("book", "remind"):
            if not binding:
                self.ask_for_book(ext, code)
                return
            if action == "book":
                self.cmd_book(ext, binding, code)
            else:
                self.cmd_remind(ext, binding, code)
            return
        if action is None and cmd.is_command(text) and not binding:
            # An unknown command with no book: say how to get one rather than
            # filing the typo as a memory.
            self.ask_for_book(ext, code)
            return
        if action is None and not binding and looks_like_key(text):
            # /key was tapped and the key arrived as its own message. That is
            # how a menu button invites people to behave, so take it as the key
            # instead of answering with the syntax lesson again.
            self.cmd_key(ext, text, code)
            return

        if not binding:
            self.ask_for_book(ext, code)
            return

        self.tg.notify_looking(ext)
        try:
            out = self.brain.turn(binding["passkey"], text)
        except BrainError:
            self.say(ext, lang.bot_string(code, "down"))
            return
        if not out.get("ok"):
            self.say(ext, lang.bot_string(code, "error", out.get("error") or "?"))
            return
        say = out.get("say") or ""
        self.say(ext, say)

    def inbound_loop(self):
        pending, offset = self.pending_at_start()
        while not self.stop.is_set():
            if pending:
                updates, pending = pending, []
            else:
                try:
                    updates = self.tg.updates(offset=offset, timeout=30)
                except TelegramError as exc:
                    print("[inbound] %s" % exc, flush=True)
                    time.sleep(5)
                    continue
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                payload = update.get("message")
                if not payload:
                    continue
                try:
                    self.handle_message(payload)
                except Exception:  # noqa: BLE001
                    # One bad message must not kill the loop. The traceback goes
                    # to the log, the person gets a short apology.
                    print("[inbound] crash:\n%s" % traceback.format_exc(), flush=True)

    def pending_at_start(self):
        """What is waiting when the bot comes up, and what to do with it.

        This used to throw the whole backlog away, to avoid replaying a day of
        messages after an outage and paying for every write. That was wrong for
        this product. A notebook that silently eats what you wrote while it was
        restarting has failed at the one thing it promised, and it failed
        quietly, which is worse.

        So: anything recent is handled, anything old is left behind. Ten minutes
        covers a restart, a deploy and a crash. It does not cover an eight-hour
        outage, where replaying everything would post a pile of stale turns.

        Returns (fresh updates, the next offset to poll from). Everything is
        confirmed either way, so the old ones do not come back on every restart.
        """
        try:
            got = self.tg.updates(offset=0, timeout=0)
        except TelegramError as exc:
            print("[inbound] tidak bisa baca antrean: %s" % exc, flush=True)
            return [], 0
        if not got:
            return [], 0
        cutoff = time.time() - STALE_AFTER.total_seconds()
        fresh, stale = [], 0
        for update in got:
            when = (update.get("message") or {}).get("date") or 0
            if when >= cutoff:
                fresh.append(update)
            else:
                stale += 1
        try:
            self.tg.updates(offset=got[-1]["update_id"] + 1, timeout=0)
        except TelegramError:
            pass
        if stale:
            print("[inbound] %d pesan lama (lebih dari %d menit) dilewati"
                  % (stale, STALE_AFTER.total_seconds() // 60), flush=True)
        if fresh:
            print("[inbound] %d pesan dari antrean diteruskan" % len(fresh), flush=True)
        return fresh, got[-1]["update_id"] + 1

    # ---- outbound reminders ---------------------------------------------

    def due_reminders(self, out, external_id, now):
        """Which reminders in this state are worth sending right now.

        `spoken` is the notebook's answer, the local file is this process's
        answer, and both are needed: the notebook knows a reminder was delivered
        even if this file was lost, and this file knows one was delivered even if
        the Walrus write is still sitting in the outbox.
        """
        out_list = []
        for rem in out.get("reminders") or []:
            fire = (rem.get("fire") or "").strip()
            if not fire:
                continue
            tz = rem.get("timezone") or out.get("timezone") or timezones.DEFAULT_TIMEZONE
            now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            if not timezones.due_in_timezone(fire, now_utc, tz):
                continue
            try:
                fire_dt = datetime.fromisoformat(fire)
                fire_identity = timezones.reminder_identity(fire, tz)
            except ValueError:
                continue
            now_local = timezones.local_timestamp(now_utc, tz)
            if now_local - fire_dt.replace(tzinfo=None) > IGNORE_OLDER_THAN:
                continue
            if rem.get("spoken"):
                continue
            if self._already_sent(external_id, fire_identity):
                continue
            out_list.append((fire_identity, fire, rem))
        out_list.sort(key=lambda pair: pair[1])
        return out_list[:PER_CHAT_PER_PASS]

    def reminder_pass(self):
        now = datetime.now(timezone.utc)
        rows = self.bindings.all()
        for external_id, binding in rows.items():
            if not binding.get("passkey"):
                continue
            try:
                out = self.brain.state(binding["passkey"])
            except BrainError as exc:
                print("[remind] %s: %s" % (external_id, exc), flush=True)
                continue
            if not out.get("ok"):
                continue
            code = out.get("lang") or binding.get("lang") or lang.DEFAULT_LANG
            shop = (((out.get("state") or {}).get("pack") or {}).get("name") or "").strip()
            for fire_ref, fire, rem in self.due_reminders(out, external_id, now):
                body = "%s\n\n%s: %s\n%s" % (
                    lang.bot_string(code, "debt_head"),
                    rem.get("person") or "?",
                    rem.get("text") or "",
                    rem.get("date") or fire)
                if shop:
                    # A reminder arrives on its own, hours after the last
                    # message, so it has to say whose book it came from.
                    body = "%s\n\n%s" % (lang.bot_string(code, "shop_head", shop), body)
                if not self.say(external_id, body):
                    # Sending failed, so it is not delivered. Leave it for the
                    # next pass rather than recording a delivery that never was.
                    continue
                self._mark_sent(external_id, fire_ref)
                try:
                    self.brain.fired(binding["passkey"], fire,
                                     text=rem.get("text") or "delivered")
                except BrainError as exc:
                    print("[remind] fired write queued: %s" % exc, flush=True)
                print("[remind] sent %s to %s" % (fire_ref, external_id), flush=True)

    def reminder_loop(self):
        while not self.stop.is_set():
            try:
                self.reminder_pass()
            except Exception:  # noqa: BLE001
                # A reminder loop that dies takes the alarm with it, and an alarm
                # that stops without saying so is worse than one that never rang.
                print("[remind] crash:\n%s" % traceback.format_exc(), flush=True)
            self.stop.wait(REMINDER_EVERY)

    # ---- lifecycle -------------------------------------------------------

    def start(self):
        me = self.tg.whoami()
        print("bot      : @%s (%s)" % (me.get("username"), me.get("id")), flush=True)
        health = self.brain.health()
        print("notebook : %s packs, %s queued" % (health.get("packs"),
                                                  health.get("queued")), flush=True)
        print("bindings : %d chat(s)" % len(self.bindings.all()), flush=True)
        self.register_commands()
        threading.Thread(target=self.reminder_loop, daemon=True).start()
        print("listening. ctrl-c to stop.", flush=True)
        try:
            self.inbound_loop()
        except KeyboardInterrupt:
            self.stop.set()
            print("\nstopped.", flush=True)

    def register_commands(self):
        """Hand the / menu to Telegram, built from commands.py.

        English is the default list, Indonesian is registered as the list for
        Indonesian phones. The names are the same in both; only the one-line
        description changes. A failure here is not fatal, because the bot still
        answers every command by text.
        """
        rows = cmd.help_rows()
        try:
            count = self.tg.set_commands(
                [(name, lang.bot_string("en", "cmd_" + action))
                 for name, action in rows])
            print("menu     : %d perintah (inggris, default)" % count, flush=True)
            self.tg.set_commands(
                [(name, lang.bot_string("id", "cmd_" + action))
                 for name, action in rows], language_code="id")
            print("menu     : daftar indonesia terdaftar", flush=True)
        except TelegramError as exc:
            print("menu     : gagal daftar (%s), bot tetap jalan" % exc, flush=True)


def main():
    load_env()
    # Log to a file as well as the screen. Printing alone only ends up somewhere
    # if whoever started the process keeps the pipe open, and a bot started by
    # hand can end up with nobody reading it. "Did my message arrive" has to be
    # a question the log answers by itself.
    sys.stdout = sys.stderr = Tee(LOG_PATH, sys.stdout)
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    base = os.environ.get("FIELDPACK_BASE") or "http://127.0.0.1:8770"
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set in .env")
    Bot(token, base).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
