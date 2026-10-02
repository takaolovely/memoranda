"""Alarm, end to end, without sending anything to a real Telegram chat.

Builds a pack, plants a reminder that came due yesterday, then runs the bot's
real reminder pass with only the send step swapped for a recorder. What gets
verified is everything except the wire:

  1. the notebook reports the reminder as due
  2. the pass picks it up and produces the right message
  3. the delivery is written down in the local file AND in Walrus
  4. a second pass sends nothing, because it already went

Run:  .venv/bin/python test_alarm_live.py
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import packlib  # noqa: E402
import server  # noqa: E402
from brain import Brain  # noqa: E402
from channels.base import BindingStore  # noqa: E402
from memoranda_bot import Bot  # noqa: E402

BASE = "http://127.0.0.1:8770"
PASSED, FAILED = [], []


def check(label, got, want=True):
    if got == want:
        PASSED.append(label)
        print("ok   %s" % label)
    else:
        FAILED.append(label)
        print("FAIL %s\n     dapat: %r\n     harus: %r" % (label, got, want))


def main():
    brain = Brain(BASE)
    health = brain.health()
    print("notebook : %s pack, %s antrean\n" % (health.get("packs"), health.get("queued")))

    made = brain.create_pack(biz="ac_service", name="Alarm Test", lang="id")
    key = made.get("passkey") or ""
    check("pack uji dibuat", bool(key))
    if not key:
        return 1

    meta = server.pack_of(key)
    store = server.build_store(meta["namespace"])

    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT09:00:00")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT08:00:00")

    # A person with money outstanding, then a reminder that has come due. Written
    # with the same render() and the same store the server uses, so this is the
    # shape a real turn produces and not a hand-made fixture.
    lines = [
        packlib.render("person", "pak jojo", p="pak_jojo", name="pak_jojo"),
        packlib.render("job", "servis ac", job="job1", p="pak_jojo", s="ac",
                       amount=250000, type="servis", at=yesterday),
        packlib.render("rem", "tagih sisa utang", p="pak_jojo", s="ac",
                       kind="collect", fire=past),
    ]
    store.write_many(lines)

    out = brain.state(key)
    rems = out.get("reminders") or []
    check("notebook melaporkan 1 pengingat", len(rems), 1)
    if rems:
        check("pengingat belum dibunyikan", rems[0].get("spoken"), False)
        check("jamnya beneran udah lewat", rems[0].get("fire"), past)
        # The line stores the slug; what is shown has to be the display name, or
        # the panel reads "tagih sisa utang" with nobody it belongs to.
        check("yang ditampilkan nama, bukan slug", rems[0].get("person"), "pak jojo")
        check("slug aslinya tetap ada", rems[0].get("slug"), "pak_jojo")

    # --- the pass, with the wire swapped out -------------------------------
    root = tempfile.mkdtemp(prefix="memoranda-alarm-")
    bot = Bot("123:abc", BASE,
              bindings=BindingStore(path=os.path.join(root, "bindings.json")),
              sent_path=os.path.join(root, "sent.json"))
    bot.bindings.bind("tg:999", key, meta["pack_id"], "id")

    sent = []
    bot.tg.send = lambda ext, text: (sent.append((ext, text)), 1)[1]

    bot.reminder_pass()
    check("sekali pass, satu pesan terkirim", len(sent), 1)
    if sent:
        ext, body = sent[0]
        check("dikirim ke chat yang benar", ext, "tg:999")
        check("isinya ada nama orang", "pak jojo" in body, True)
        check("isinya ada perintahnya", "tagih sisa utang" in body, True)
        print("\n--- isi pesan yang bakal lu terima ---")
        print(body)
        print("--- habis ini ---\n")

    check("dicatat di file lokal", bot._already_sent("tg:999", past), True)

    after = brain.state(key)
    spoken = [r for r in (after.get("reminders") or []) if r.get("fire") == past]
    check("tercatat juga di Walrus", bool(spoken) and spoken[0].get("spoken"), True)

    bot.reminder_pass()
    check("pass kedua tidak ngirim lagi", len(sent), 1)

    check("pass kedua tidak nulis ulang di Walrus",
          len([r for r in (brain.state(key).get("reminders") or [])
               if r.get("fire") == past and r.get("spoken")]), 1)

    print("\n%d lolos, %d gagal" % (len(PASSED), len(FAILED)))
    if FAILED:
        for label in FAILED:
            print("  gagal: %s" % label)
        return 1
    print("all alarm tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
