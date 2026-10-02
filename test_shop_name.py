"""Nama toko harus kebaca di ketiga tempat yang dipakai orang.

Dulu header web cuma bilang jenis usaha, bahasa, dan mata uang, dan bot cuma
bilang "BUKU" atau "PENGINGAT". Dua buku beda kelihatan sama persis. Tes ini
mengunci tiga jalur yang menampilkan nama toko supaya tidak hilang lagi.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lang      # noqa: E402
import packlib    # noqa: E402

DATA = os.path.join(HERE, "data")
checks = []


def ok(name, condition, extra=""):
    checks.append((name, bool(condition), extra))
    print("%s %s%s" % ("ok  " if condition else "FAIL", name,
                       (" -> %s" % extra) if extra and not condition else ""))


def journal_lines(path):
    if not os.path.exists(path):
        return []
    return [json.loads(line)["text"] for line in open(path, encoding="utf-8")
            if line.strip()]


# 1. nama toko dibaca dari bagian yang dibaca manusia, bukan dari tag
lines = journal_lines(os.path.join(DATA, "fieldpack_3619e5d9.journal.jsonl"))
if lines:
    pack = packlib.fold(lines)["pack"]
    ok("nama toko terbaca dari baris pack", pack["name"] == "Berry Repair",
       repr(pack.get("name")))
    ok("nama toko ikut di ringkasan state",
       packlib.summary(packlib.fold(lines))["pack"].get("name") == "Berry Repair")

strong = journal_lines(os.path.join(DATA, "fieldpack_993c8969.journal.jsonl"))
if strong:
    ok("toko kedua kebaca juga",
       packlib.fold(strong)["pack"]["name"] == "Strong Ar")

# 2. buku tanpa nama tidak boleh menampilkan id heksa sebagai nama toko
blank = ["pack 9c30f2af timezone=Asia/Jakarta #k:pack #pk:9c30f2af #biz:generic "
         "#pb:generic #tz:Asia/Jakarta #lang:id #cur:IDR"]
ok("buku tanpa nama tidak menampilkan id sebagai nama",
   packlib.fold(blank)["pack"]["name"] == "")

# 3. tag #name: menang kalau ada, supaya baris baru bisa eksplisit
explicit = ["pack Apa Saja timezone=Asia/Jakarta #k:pack #pk:deadbeef "
            "#name:Toko_Baru #biz:generic #pb:generic #tz:Asia/Jakarta "
            "#lang:id #cur:IDR"]
ok("tag #name: menang atas teks",
   packlib.fold(explicit)["pack"]["name"] == "Toko Baru",
   repr(packlib.fold(explicit)["pack"]["name"]))

# 4. kalimat yang dipakai bot ada di dua bahasa, jadi tidak ada bahasa yang
#    kehilangan baris nama toko
for code in ("id", "en"):
    text = lang.bot_string(code, "shop_head", "Toko Contoh")
    ok("bot_string shop_head [%s] keisi" % code,
       "Toko Contoh" in text and "%s" not in text, repr(text))
ok("shop_head ada di kedua tabel bot",
   all("shop_head" in lang.BOT_STRINGS[c] for c in ("id", "en")))

# 5. halaman web benar-benar menampilkan dan menyembunyikan chip nama toko
page = open(os.path.join(HERE, "web", "index.html"), encoding="utf-8").read()
ok("chip nama toko ada di header", 'id="nameTag"' in page)
ok("chip nama toko disembunyikan saat kosong",
   re.search(r'id="nameTag"[^>]*class="[^"]*hidden"', page) is not None
   or 'class="tag shop hidden"' in page)
ok("chip nama toko diisi dari state.pack.name",
   "setShopTag((out.state.pack && out.state.pack.name)" in page)
ok("nama toko dibersihkan waktu keluar dari buku", 'setShopTag("")' in page)

failed = [name for name, good, _ in checks if not good]
print("\n%d lolos, %d gagal" % (len(checks) - len(failed), len(failed)))
if failed:
    print("gagal: " + ", ".join(failed))
    sys.exit(1)
print("all shop name tests passed")
