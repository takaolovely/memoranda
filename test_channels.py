"""Offline tests for the channel seam and the reminder alarm.

No network, no Walrus, no token. Everything here runs in a temp directory.

Run:  .venv/bin/python test_channels.py
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lang  # noqa: E402
import commands as cmd  # noqa: E402
from brain import Brain  # noqa: E402
from channels.base import BindingStore  # noqa: E402
from channels.telegram import Telegram  # noqa: E402
from memoranda_bot import Bot, pack_lang_for  # noqa: E402

PASSED = []
FAILED = []


def pack_lang(binding, payload):
    return pack_lang_for(binding, payload)


def check(label, got, want=True):
    if got == want:
        PASSED.append(label)
        print("ok   %s" % label)
    else:
        FAILED.append(label)
        print("FAIL %s\n     dapat: %r\n     harus: %r" % (label, got, want))


def temp_bot():
    root = tempfile.mkdtemp(prefix="memoranda-chan-")
    store = BindingStore(path=os.path.join(root, "bindings.json"))
    return Bot("123:abc", "http://127.0.0.1:9", bindings=store,
               sent_path=os.path.join(root, "sent.json"))


def state_with(reminders, people=None):
    return {"ok": True, "lang": "id", "state": {"people": people or []},
            "timezone": "Asia/Jakarta", "reminders": reminders}


def rem(fire, kind="collect", spoken=False, person="pak_jojo", text="tagih",
        timezone_name="Asia/Jakarta"):
    return {"person": person, "subject": "ac", "kind": kind, "fire": fire,
            "text": text, "spoken": spoken, "date": "01 Okt",
            "timezone": timezone_name}


# ---------------------------------------------------------------------------
print("--- binding table ---")
bot = temp_bot()
check("belum ada binding", bot.bindings.get("tg:1"), None)
bot.bindings.bind("tg:1", "KUNCI", "pack1", "id")
row = bot.bindings.get("tg:1")
check("passkey tersimpan", row["passkey"], "KUNCI")
check("pack_id tersimpan", row["pack_id"], "pack1")
check("channel ditebak dari id", row["channel"], "tg")
check("jumlah binding", len(bot.bindings.all()), 1)
bot.bindings.bind("wa:62812", "KUNCI2", "pack2", "en")
check("dua saluran tidak tabrakan", len(bot.bindings.all()), 2)
check("id telega tetap utuh", bot.bindings.get("tg:1")["passkey"], "KUNCI")
check("lepas satu", bot.bindings.unbind("tg:1"), True)
check("yang lain tidak kena", bot.bindings.get("wa:62812")["passkey"], "KUNCI2")
check("lepas yang sudah lepas", bot.bindings.unbind("tg:1"), False)

root = tempfile.mkdtemp(prefix="memoranda-broken-")
broken = os.path.join(root, "bindings.json")
os.makedirs(root, exist_ok=True)
with open(broken, "w", encoding="utf-8") as fh:
    fh.write("{ini bukan json")
check("tabel rusak tidak meledak", BindingStore(path=broken).all(), {})

# ---------------------------------------------------------------------------
print("\n--- adaptor telegram ---")
tg = Telegram("123:abc")
check("external_id dari chat", tg.external_id({"chat": {"id": 555}}), "tg:555")
check("teks diambil", tg.text_of({"text": "  halo  "}), "halo")
check("teks kosong", tg.text_of({}), "")
try:
    Telegram("abc")
    check("token salah bentuk ditolak", False, True)
except Exception:  # noqa: BLE001
    check("token salah bentuk ditolak", True)

# ---------------------------------------------------------------------------
print("\n--- pengingat: mana yang bunyi ---")
bot = temp_bot()
now = datetime(2026, 10, 1, 12, 0, 0)

due = bot.due_reminders(
    state_with([rem("2026-10-01T09:00:00")]), "tg:1", now)
check("yang jamnya udah lewat dibunyikan", len(due), 1)

future = bot.due_reminders(
    state_with([rem("2026-10-05T09:00:00")]), "tg:1", now)
check("yang belum waktunya ditahan", len(future), 0)

spoken = bot.due_reminders(
    state_with([rem("2026-10-01T09:00:00", spoken=True)]), "tg:1", now)
check("yang sudah dibunyikan tidak diulang", len(spoken), 0)

ancient = bot.due_reminders(
    state_with([rem("2026-01-01T09:00:00")]), "tg:1", now)
check("yang kelamaan tidak dikejar", len(ancient), 0)

future_clock = bot.due_reminders(
    state_with([rem("2026-10-01T21:00:00")]), "tg:1",
    datetime(2026, 10, 1, 12, 1, tzinfo=timezone.utc))
check("reminder 21:00 WIB tidak bunyi jam 19:01 WIB",
      len(future_clock), 0)
at_21_wib = bot.due_reminders(
    state_with([rem("2026-10-01T21:00:00")]), "tg:1",
    datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc))
check("reminder 21:00 WIB bunyi tepat pada waktunya",
      len(at_21_wib), 1)

nofire = bot.due_reminders(
    state_with([rem("")]), "tg:1", now)
check("tanpa jam tidak dibunyikan", len(nofire), 0)

junk = bot.due_reminders(
    state_with([rem("bukan tanggal")]), "tg:1", now)
check("tanggal rusak tidak meledak", len(junk), 0)

many = bot.due_reminders(
    state_with([rem("2026-10-01T0%d:00:00" % i) for i in range(1, 6)]), "tg:1", now)
check("dibatasi 3 per pass", len(many), 3)
check("yang paling lama didahulukan", many[0][0],
      "2026-10-01T01:00:00")

# ---------------------------------------------------------------------------
print("\n--- pengingat: jangan sampai dobel ---")
bot = temp_bot()
one = state_with([rem("2026-10-01T09:00:00")])
first = bot.due_reminders(one, "tg:1", now)
check("pass pertama ambil satu", len(first), 1)
bot._mark_sent("tg:1", first[0][0])
second = bot.due_reminders(one, "tg:1", now)
check("pass kedua tidak ambil lagi", len(second), 0)
check("chat lain tidak kena catatan", bot._already_sent("tg:2", first[0][0]),
      False)

# A local sent marker written by the old bot version contains only the fire
# timestamp. It must still suppress the same legacy reminder after upgrade.
bot = temp_bot()
old_state = state_with([rem("2026-10-01T09:00:00")])
bot._mark_sent("tg:1", "2026-10-01T09:00:00")
check("marker lokal versi lama tetap mencegah kirim ulang",
      len(bot.due_reminders(old_state, "tg:1", now)), 0)

# A reminder whose timezone was captured at creation keeps that wall time even
# when the book's current setting later changes.
bot = temp_bot()
frozen = state_with([rem("2026-10-01T09:00:00")])
frozen["reminders"][0]["timezone"] = "Asia/Jakarta"
frozen["timezone"] = "Asia/Makassar"
before_wib_9 = datetime(2026, 10, 1, 1, 59, tzinfo=timezone.utc)
at_wib_9 = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
check("reminder lama bertag tetap ikut zona saat dibuat",
      len(bot.due_reminders(frozen, "tg:2", before_wib_9)), 0)
check("reminder bertag bunyi pada jam lokal tersimpan",
      len(bot.due_reminders(frozen, "tg:2", at_wib_9)), 1)

fresh_zone = state_with([rem("2026-10-01T09:00:00", timezone_name="Asia/Makassar")])
at_wita_9 = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
check("new WITA reminder due at its local 09:00",
      len(bot.due_reminders(fresh_zone, "tg:3", at_wita_9)), 1)

# ---------------------------------------------------------------------------
print("\n--- bahasa teks bot ---")
check("id punya teks", lang.bot_string("id", "book_head"), "BUKU")
check("en punya teks", lang.bot_string("en", "book_head"), "BOOK")
check("bahasa tak dikenal -> english", lang.bot_string("fr", "book_head"), "BOOK")
check("kunci hilang -> kunci itu sendiri", lang.bot_string("id", "tidak_ada"), "tidak_ada")
check("kunci bot masuk ke templat", "ABC" in lang.bot_string("id", "new_ok", "ABC"), True)
check("ganti nama brand tidak ngaruh ke bot",
      lang.bot_string("id", "hi").count("Memoranda"), 0)

check("dua bahasa lengkap sama",
      sorted(lang.BOT_STRINGS["id"]) == sorted(lang.BOT_STRINGS["en"]), True)

# ---------------------------------------------------------------------------
print("\n--- bahasa per chat ---")
check("binding indonesia menang", pack_lang({"lang": "id"}, {"from": {"language_code": "en-US"}}), "id")
check("tanpa binding pakai locale id", pack_lang(None, {"from": {"language_code": "id"}}), "id")
check("locale lama 'in' tetap id", pack_lang(None, {"from": {"language_code": "in-ID"}}), "id")
check("locale lain -> english", pack_lang(None, {"from": {"language_code": "pt-BR"}}), "en")
check("tanpa locale -> english", pack_lang(None, {}), "en")

# ---------------------------------------------------------------------------
print("\n--- brain ---")
b = Brain("http://127.0.0.1:8770/")
check("garis miring dobel dibuang", b.base, "http://127.0.0.1:8770")
try:
    Brain("http://127.0.0.1:9").health(timeout=3)
    check("server mati melempar BrainError", False, True)
except Exception as exc:  # noqa: BLE001
    check("server mati melempar BrainError", type(exc).__name__, "BrainError")

# ---------------------------------------------------------------------------
print("\n--- perintah bisa diganti dari repo ---")
check("nama yang ditampilkan itu inggris", cmd.shown("new"), "/new")
check("resolve nama tampil", cmd.resolve("/new"), "new")
check("resolve alias indonesia", cmd.resolve("/baru"), "new")
check("resolve huruf besar", cmd.resolve("/BARU"), "new")
check("resolve dengan handle bot", cmd.resolve("/baru@memorandachatbot"), "new")
check("resolve yang gak dikenal", cmd.resolve("/apalah"), None)
check("resolve teks kosong", cmd.resolve(""), None)
check("resolve kata biasa", cmd.resolve("pak jojo servis ac"), None)
check("spasi di depan tetap kena", cmd.resolve("  /new  "), "new")

check("kenali perintah", cmd.is_command("/new"), True)
check("teks biasa bukan perintah", cmd.is_command("servis ac"), False)
check("string kosong bukan perintah", cmd.is_command(""), False)

check("argumen diambil", cmd.argument_of("/key Kd9xAb12"), "Kd9xAb12")
check("argumen kosong", cmd.argument_of("/key"), "")
check("argumen dengan spasi", cmd.argument_of("/key abc def"), "abc def")

rows = cmd.help_rows()
check("help punya semua aksi", sorted(a for _n, a in rows), sorted(cmd.HELP_ORDER))
check("help pakai nama tampil", rows[0], ("/new", "new"))
check("setiap nama punya aksi yang valid",
      all(cmd.resolve(shown_name) == action for action, shown_name, _a in cmd.COMMANDS),
      True)
check("alias tidak tabrakan dengan nama lain",
      len(cmd.known_names()) == len(set(cmd.known_names())), True)

print("\n--- teks bantuan gak bisa bohong ---")
for code in ("id", "en"):
    missing = [a for a in cmd.HELP_ORDER
               if ("cmd_%s" % a) not in lang.BOT_STRINGS[code]]
    check("%s punya deskripsi semua perintah" % code, missing, [])

# Kalau ada pesan yang nulis nama perintah langsung, ganti nama di commands.py
# bakal bikin pesannya nyasar. Ini yang nahan itu.
named = []
for code in ("id", "en"):
    for key, value in lang.BOT_STRINGS[code].items():
        for name in cmd.known_names():
            if name in value:
                named.append("%s/%s" % (code, key))
check("tidak ada pesan yang nulis nama perintah langsung", sorted(set(named)), [])

bot = temp_bot()
outbox = []
bot.tg.send = lambda ext, text: (outbox.append(text), 1)[1]
bot.cmd_help("tg:1", "id")
help_id = outbox[0]
check("help id memuat /new", "/new" in help_id, True)
check("help id memuat /key", "/key" in help_id, True)
check("help id memuat deskripsi indonesia", "bikin buku baru" in help_id, True)
check("help id tidak menyebut command lama", "/baru" in help_id, False)
check("help id menyebut kunci butuh argumen", "/key <key>" in help_id, True)

outbox.clear()
bot.cmd_help("tg:1", "en")
help_en = outbox[0]
check("help en memuat semua perintah",
      all(cmd.shown(a) in help_en for a in cmd.HELP_ORDER), True)
check("help en pakai deskripsi inggris", "make a new book" in help_en, True)
check("help explains offer-again is opt-in",
      "offer-again notes are opt-in" in help_en, True)

outbox.clear()
bot.bindings.bind("tg:1", "KUNCI", "pack1", "en")
bot.brain.state = lambda _key: state_with([], [])
bot.cmd_book("tg:1", bot.bindings.get("tg:1"), "en")
check("/book explains manual offer-again reminders", "only created when you ask" in outbox[0], True)

outbox.clear()
bot.ask_for_book("tg:1", "en")
check("ajakan bikin buku memakai nama dari tabel", "/new" in outbox[0], True)
check("ajakan bikin buku tidak nulis nama sendiri", "/baru" in outbox[0], False)

print("\n%d lolos, %d gagal" % (len(PASSED), len(FAILED)))
if FAILED:
    for label in FAILED:
        print("  gagal: %s" % label)
    sys.exit(1)
print("all channel tests passed")
