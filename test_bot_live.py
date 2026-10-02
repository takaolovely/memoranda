"""Jalur pesan masuk, ditest persis seperti orang ngetik di Telegram.

Yang offline: sambungan Telegram dan tulisannya ke layar. Yang beneran: seluruh
handle_message, server buku yang hidup, dan berkas binding.

Tes ini ada karena satu pesan /key yang gak pernah kebales. Waktu itu gak ada
tes yang nyetir jalur masuk, jadi gak ada yang ketahuan.

Run:  .venv/bin/python test_bot_live.py
"""

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from brain import Brain  # noqa: E402
from channels.base import BindingStore  # noqa: E402
from memoranda_bot import Bot, looks_like_key  # noqa: E402

BASE = "http://127.0.0.1:8770"
PASSED, FAILED = [], []


def check(label, got, want=True):
    if got == want:
        PASSED.append(label)
        print("ok   %s" % label)
    else:
        FAILED.append(label)
        print("FAIL %s\n     dapat: %r\n     harus: %r" % (label, got, want))


def update(chat_id, text, age_seconds=0, lang_code="id"):
    """Satu update Telegram, bentuk aslinya.

    handle_message makan dict pesannya, bukan dict update-nya. Salah baca satu
    lapis ini bikin teksnya terbaca kosong dan pesannya dibuang diam-diam, yang
    persis kelihatan seperti bot yang tidak menjawab.
    """
    return {"update_id": int(time.time() * 1000) % 1000000,
            "message": {"message_id": 1,
                        "date": int(time.time()) - age_seconds,
                        "from": {"id": chat_id, "language_code": lang_code},
                        "chat": {"id": chat_id, "type": "private"},
                        "text": text}}


class BotHarness:
    """Bot asli, dengan Telegram diganti buku catatan."""

    def __init__(self, root):
        self.out = []
        self.bot = Bot("123:abc", BASE,
                       bindings=BindingStore(path=os.path.join(root, "bindings.json")),
                       sent_path=os.path.join(root, "sent.json"))
        self.bot.tg.send = lambda ext, text: (self.out.append((ext, text)), 1)[1]
        self.bot.tg.notify_looking = lambda ext, action="typing": True

    def feed(self, chat_id, text, lang_code="id"):
        self.out.clear()
        self.bot.handle_message(update(chat_id, text, lang_code=lang_code)["message"])
        return self.out[-1][1] if self.out else ""


def main():
    brain = Brain(BASE)
    root = tempfile.mkdtemp(prefix="memoranda-bot-")
    h = BotHarness(root)
    chat = 777001

    # ---- pesan masuk yang paling sering kejadian --------------------------
    check("ketik apa aja tanpa buku -> disuruh bikin",
          "/new" in h.feed(chat, "pak jojo servis ac 500rb"), True)

    # Pemakai palsu di sini berbahasa Indonesia, jadi keterangannya Indonesia.
    # Nama perintahnya tetap sama, itu bagian yang sengaja tidak ikut bahasa.
    check("/start -> bantuan bahasa indonesia",
          "Yang bisa lu ketik" in h.feed(chat, "/start"), True)
    check("nama perintah tetap inggris walau bantuan indonesia",
          "/new" in h.feed(chat, "/start") and "/baru" not in h.feed(chat, "/start"),
          True)
    check("hp berbahasa inggris -> bantuan inggris",
          "What you can type" in h.feed(chat, "/help", lang_code="en"), True)

    # ---- kunci buku yang beneran ada --------------------------------------
    made = brain.create_pack(biz="ac_service", name="Tele Test", lang="id")
    key = made["passkey"]

    reply = h.feed(chat, "/key %s" % key)
    check("/key kunci valid -> nyambung", "Nyambung" in reply, True)
    check("binding tercatat", h.bot.bindings.get("tg:%d" % chat) is not None, True)
    check("yang tersimpan kuncinya benar",
          (h.bot.bindings.get("tg:%d" % chat) or {}).get("passkey"), key)

    # ---- sekarang catatan beneran masuk -----------------------------------
    reply = h.feed(chat, "pak budi servis ac 200rb belum bayar")
    check("catatan masuk dan dibalas", len(reply) > 5, True)
    check("balasannya nyebut orangnya", "budi" in reply.lower(), True)

    reply = h.feed(chat, "/book")
    check("/book nampilin orangnya", "budi" in reply.lower(), True)
    check("/book nampilin utangnya", "200" in reply, True)

    reply = h.feed(chat, "/remind")
    check("/remind jalan tanpa error", "PENGINGAT" in reply.upper(), True)

    # ---- kunci yang salah -------------------------------------------------
    reply = h.feed(chat, "/key INI_BUKAN_KUNCI")
    check("/key salah -> bilang gak ketemu", "gak ketemu" in reply.lower(), True)
    check("binding lama tidak rusak",
          (h.bot.bindings.get("tg:%d" % chat) or {}).get("passkey"), key)

    reply = h.feed(chat, "/key")
    check("/key tanpa argumen -> contoh", "Contoh" in reply, True)
    check("/key tanpa argumen -> bilang satu pesan", "satu pesan" in reply, True)

    # ---- /key ditekan, kuncinya baru dikirim di pesan kedua ---------------
    # Ini yang bikin Caligula bingung: menu Telegram ngajak orang ngetik /key
    # dulu, lalu kuncinya di pesan berikutnya. Yang salah bukan orangnya, jadi
    # bot harus paham, bukan ngasih pelajaran sintaks lagi.
    print("\n--- /key dulu, kunci di pesan kedua ---")
    chat2 = 777002
    h.feed(chat2, "/key")
    reply = h.feed(chat2, key)
    check("kunci telanjang diterima", h.bot.bindings.get("tg:%d" % chat2) is not None, True)
    check("yang tersimpan kunci yang bener",
          (h.bot.bindings.get("tg:%d" % chat2) or {}).get("passkey"), key)
    check("langsung bisa nyatet sesudahnya",
          "budi" in h.feed(chat2, "pak budi servis ac 150rb").lower(), True)

    check("kunci ngawur yang panjang -> bilang gak ketemu",
          "gak ketemu" in h.feed(777003, "INIbukanKUNCIsamaSekali").lower(), True)
    check("catatan biasa tidak disangka kunci",
          "/new" in h.feed(777004, "pak jojo servis ac 500rb"), True)
    check("kata pendek tidak disangka kunci",
          "/new" in h.feed(777005, "halo"), True)
    check("bentuk kunci: 24 huruf campur angka", looks_like_key(key), True)
    check("bentuk kunci: kalimat biasa bukan", looks_like_key("pak jojo ac 500rb"), False)
    check("bentuk kunci: perintah bukan", looks_like_key("/key abcdefghijklmnop"), False)

    # ---- lepas ------------------------------------------------------------
    reply = h.feed(chat, "/release")
    check("/release bilang lepas", "dilepas" in reply.lower(), True)
    check("binding hilang setelah lepas", h.bot.bindings.get("tg:%d" % chat), None)
    check("sesudah lepas, teks disuruh bikin lagi",
          "/new" in h.feed(chat, "halo"), True)

    # ---- alias indonesia masih jalan --------------------------------------
    h.feed(chat, "/kunci %s" % key)
    check("alias /kunci masih nyambung",
          (h.bot.bindings.get("tg:%d" % chat) or {}).get("passkey"), key)

    # ---- antrean waktu bot baru hidup -------------------------------------
    print("\n--- antrean saat bot baru nyala ---")

    class Queue:
        """Telegram palsu yang ngasih antrean siap pakai."""

        def __init__(self, batches):
            self.batches = list(batches)
            self.calls = []

        def updates(self, offset=0, timeout=30):
            self.calls.append(offset)
            return self.batches.pop(0) if self.batches else []

    h2 = BotHarness(tempfile.mkdtemp(prefix="memoranda-queue-"))
    fresh = update(111, "/help", age_seconds=30)
    stale = update(112, "/help", age_seconds=3600)
    h2.bot.tg = Queue([[fresh, stale]])
    kept, offset = h2.bot.pending_at_start()
    check("pesan 30 detik diteruskan", [u["message"]["chat"]["id"] for u in kept], [111])
    check("pesan 1 jam dilewati", len(kept), 1)
    check("offset dikonfirmasi biar gak balik", offset, stale["update_id"] + 1)
    check("dua panggilan ke Telegram", len(h2.bot.tg.calls), 2)

    h3 = BotHarness(tempfile.mkdtemp(prefix="memoranda-queue2-"))
    h3.bot.tg = Queue([[]])
    kept, offset = h3.bot.pending_at_start()
    check("antrean kosong aman", (kept, offset), ([], 0))

    print("\n%d lolos, %d gagal" % (len(PASSED), len(FAILED)))
    if FAILED:
        for label in FAILED:
            print("  gagal: %s" % label)
        return 1
    print("all bot live tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
