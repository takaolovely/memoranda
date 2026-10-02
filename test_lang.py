"""Offline tests for the language layer. No model calls, no network.

What is being checked here is the part of the language lock that cannot drift:
the words the code writes. The words the model writes are measured separately by
probe_lang.py, because a test cannot prove a model obeys a prompt, only measure
how often it does.

Run:  .venv/bin/python test_lang.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lang  # noqa: E402
import packlib  # noqa: E402
import parse  # noqa: E402

FAILS = []


def check(name, got, want):
    if got == want:
        print("ok   %s" % name)
    else:
        print("FAIL %s\n       got  %r\n       want %r" % (name, got, want))
        FAILS.append(name)


# --- what a typed language turns into ---------------------------------------

check("indonesian", lang.resolve_lang("Indonesian"), ("id", "Bahasa Indonesia"))
check("inggris", lang.resolve_lang("inggris"), ("en", "English"))
check("english", lang.resolve_lang("english"), ("en", "English"))
check("kosong jatuh ke indonesia", lang.resolve_lang(""), ("id", "Bahasa Indonesia"))
check("bahasa lain lewat apa adanya", lang.resolve_lang("Español"), ("xx", "Español"))
check("bahasa lain dirapikan", lang.resolve_lang("  hindi  "), ("xx", "hindi"))
check("nama prompts untuk bahasa lain", lang.prompt_name("xx", "Español"), "Español")
check("tanpa nama pun tetap masuk akal",
      lang.prompt_name("xx", ""), "the language the worker used")

# --- the check that refuses a wrong-language answer -------------------------

check("inggris terdeteksi", lang.detect("He still owes 150k for the last job"), "en")
check("indonesia terdeteksi", lang.detect("Dia masih utang 150rb buat kerjaan kemarin"), "id")
check("spanyol terdeteksi", lang.detect("Todavia debe 150 por el trabajo"), "es")
check("devanagari menang lewat huruf", lang.detect("अभी भी बाकी है"), "hi")
check("jawaban pendek tidak dipaksa", lang.detect("Oke."), None)

check("jawaban inggris lolos di pack inggris",
      lang.conforms("He owes 150k", "en")[0], True)
check("jawaban indonesia ditolak di pack inggris",
      lang.conforms("Dia masih utang 150rb ya", "en")[0], False)
check("jawaban inggris ditolak di pack indonesia",
      lang.conforms("He still owes 150k for the job", "id")[0], False)
check("nama pelanggan tidak dianggap bahasa lain",
      lang.conforms("Pak Asep still owes 150k", "en")[0], True)
check("bahasa yang tidak kami punya ditandai belum terverifikasi",
      lang.conforms("Todavia debe 150", "xx", "Español")[2], False)
check("huruf devanagari dicek walau bahasanya tidak kami punya",
      lang.conforms("अभी भी बाकी है", "xx", "hindi")[0], True)

# --- money and dates in the shape each language writes them -----------------

check("rupiah gaya indonesia", [lang.money(n, "id") for n in
                                (250000, 1500000, 2500, 0)],
      ["250rb", "1,5jt", "2500", "0"])
check("rupiah gaya inggris", [lang.money(n, "en") for n in
                              (250000, 1500000, 2500, 0)],
      ["250k", "1.5m", "2,500", "0"])
check("rupiah bahasa lain", lang.money(150000, "xx"), "150,000")

# --- money as a setting, not a guess ---------------------------------------
# A bare "150" is 150 ribu in rupiah and 150 dollars in dollars. Nothing in the
# number says which, so the book is told once instead of asked every time.

check("dolar menempel di angka", lang.money(150, "en", "USD"), "$150")
check("dolar di halaman indonesia juga", lang.money(150, "id", "USD"), "$150")
check("rupiah tidak dapat tanda Rp",
      lang.money(150000, "id", "IDR"), "150rb")
check("tanpa setelan, bentuknya tidak berubah", lang.money(150, "en"), "150")
check("setelan kosong ikut bahasa", lang.resolve_currency("", "en"), "USD")
check("setelan kosong bahasa indonesia", lang.resolve_currency("", "id"), "IDR")
check("ditulis idr tetap idr", lang.resolve_currency("idr", "en"), "IDR")
check("ditulis dolar", lang.resolve_currency("dollars", "id"), "USD")
check("kode asing dibiarkan apa adanya", lang.resolve_currency("eur", "en"), "EUR")

_line = packlib.render("pack", "pack x", pk="aaaa1111", biz="ac", pb="ac_service",
                       tz="Asia/Jakarta", lang="en", cur="USD",
                       at=datetime(2026, 9, 27, 10, 0, 0))
_folded = packlib.fold([_line])
check("uang tersimpan di baris pack", _folded["currency"], "USD")
check("uang terbaca di state pack", _folded["pack"]["currency"], "USD")
_old = packlib.fold([packlib.render("pack", "pack x", pk="aaaa1111", biz="ac",
                                    pb="ac_service", tz="Asia/Jakarta", lang="id",
                                    at=datetime(2026, 9, 20, 10, 0, 0))])
check("buku lama tanpa setelan uang tidak error", _old["currency"], "")
check("singkatan bulan ikut bahasa",
      (lang.short_date(datetime(2026, 10, 1), "id"),
       lang.short_date(datetime(2026, 10, 1), "en")),
      ("01 Okt", "01 Oct"))

# --- the strings the code writes, per language ------------------------------

check("pertanyaan angkanya inggris",
      lang.t("en", "ask_amount_bare", "250", "250", "250"),
      "That number is 250. Did you mean 250 thousand or 250?")
check("teks tak dikenal jatuh ke indonesia", lang.t("xx", "ask_person"),
      "Nama pelanggannya siapa?")
check("tombol ikut bahasa", lang.ui_bundle("en")["ui_send"], "Send")
check("tombol indonesia", lang.ui_bundle("id")["ui_send"], "Kirim")
check("bundel bahasa lain pakai tombol inggris",
      lang.ui_bundle("xx")["ui_send"], "Send")
check("setiap kunci ui ada di semua tabel",
      sorted(k for k in lang.STRINGS["id"] if k.startswith("ui_"))
      == sorted(k for k in lang.STRINGS["en"] if k.startswith("ui_")), True)
check("setiap kunci non-ui juga",
      sorted(k for k in lang.STRINGS["id"] if not k.startswith("ui_"))
      == sorted(k for k in lang.STRINGS["en"] if not k.startswith("ui_")), True)
for _code in ("id", "en"):
    for _key in ("ui_telegram_title", "ui_telegram_note", "ui_telegram_open",
                 "ui_telegram_step1", "ui_telegram_step2", "ui_telegram_step3"):
        check("telegram onboarding %s %s" % (_code, _key),
              bool(lang.ui_bundle(_code).get(_key)), True)

# --- the plan in another language -------------------------------------------

TODAY = datetime(2026, 9, 24, 10, 0, 0)

proposal = {
    "intent": "log", "person": "Mr Budi", "subject": "living room AC",
    "subject_type": "ac_unit", "job_type": "servis", "date_text": "21 sep",
    "date_in_days": None, "followup_after_days": None,
    "items": [{"kind": "job", "amount_text": "150"}],
    "_raw": "21 sep serviced Mr Budi living room AC, freon 150",
}
# The language picks the default money, and the money decides whether a bare
# number is a question at all. In a dollar book a bare 150 is 150 dollars, and
# asking "did you mean 150 thousand" there is the book arguing with somebody who
# already answered. This check used to assert the question, which is how the
# question survived this long.
en_plan = parse.plan(proposal, {"people": {}}, TODAY, lang_code="en")
check("buku dolar: angka telanjang tidak ditanya", en_plan["action"], "commit")
check("buku dolar: 150 berarti 150 dolar",
      [e["amount"] for e in en_plan["entries"] if e["kind"] == "job"], [150])
check("buku dolar: uangnya dolar", en_plan["currency"], "USD")

# The same English words in a rupiah book still get asked about, because the
# question is about the money and not about the language. Somebody in Jakarta
# reading an English page is still paid in rupiah.
en_idr = parse.plan(proposal, {"people": {}, "currency": "IDR"}, TODAY, lang_code="en")
check("rupiah berbahasa inggris tetap ditanya", en_idr["action"], "confirm")
check("pertanyaannya inggris, bukan indonesia",
      en_idr["question"], "That number is 150. Did you mean 150 thousand or 150?")

id_plan = parse.plan(proposal, {"people": {}}, TODAY, lang_code="id")
check("pertanyaan indonesia tetap indonesia",
      id_plan["question"], "Angkanya 150. Maksudnya 150 ribu atau 150 rupiah?")

solved = dict(proposal, items=[{"kind": "job", "amount_text": "150rb"}])
en_lines = parse.lines_for(parse.plan(solved, {"people": {}}, TODAY, lang_code="en"),
                           lang_code="en")
check("tanpa interval tidak ada offer-again otomatis",
      [packlib.kind_of(l) for l in en_lines if packlib.kind_of(l) == "rem"], [])
id_explicit = dict(solved, followup_after_days=90)
id_lines = parse.lines_for(parse.plan(id_explicit, {"people": {}}, TODAY, lang_code="id"),
                           lang_code="id")
check("interval eksplisit membuat reminder dalam bahasa pack",
      [packlib.body_of(l) for l in id_lines if packlib.kind_of(l) == "rem"],
      ["tawarin lagi living room AC"])
en_lines_explicit = parse.lines_for(
    parse.plan(dict(solved, followup_after_days=90), {"people": {}}, TODAY, lang_code="en"),
    lang_code="en")
check("interval eksplisit membuat reminder dalam bahasa Inggris",
      [packlib.body_of(l) for l in en_lines_explicit if packlib.kind_of(l) == "rem"],
      ["offer the living room AC job again"])

# --- dates arrive as numbers, so no language table has to be right ----------

multi = {
    "intent": "log", "person": "pak asep", "subject": None, "subject_type": "ac_unit",
    "job_type": "servis", "date_text": None, "date_in_days": None,
    "followup_after_days": None,
    "items": [{"kind": "job", "amount_text": "250rb"},
              {"kind": "payment", "amount_text": "100", "when_in_days": 0},
              {"kind": "promise", "when_text": "next week", "when_in_days": 7,
               "amount_text": None}],
    "_raw": "pak asep owes 250k, paid 100 today, rest next week",
}
multi_plan = parse.plan(multi, {"people": {}}, TODAY, lang_code="en")
check("janji next week jadi 7 hari dari hitungan model, bukan tabel kata",
      [e["when"].strftime("%Y-%m-%d") for e in multi_plan["entries"]
       if e["kind"] == "promise"], ["2026-10-01"])
check("bayar hari ini", [e["when"].strftime("%Y-%m-%d") for e in multi_plan["entries"]
                         if e["kind"] == "pay"], ["2026-09-24"])

relative = dict(multi, items=[{"kind": "job", "amount_text": "250rb"},
                              {"kind": "promise", "when_text": "próxima semana",
                               "when_in_days": 7}])
check("bahasa yang tabelnya tidak ada pun tetap dapat tanggal benar",
      [e["when"].strftime("%Y-%m-%d") for e in
       parse.plan(relative, {"people": {}}, TODAY, lang_code="xx")["entries"]
       if e["kind"] == "promise"], ["2026-10-01"])

# --- the bugs the language probe turned up ----------------------------------

split = {
    "intent": "log", "person": "Mr Budi", "subject": "living room AC",
    "subject_type": "ac_unit", "job_type": "servis", "date_text": "21 sep",
    "date_in_days": None, "followup_after_days": None,
    "items": [{"kind": "job", "amount_text": None},
              {"kind": "job", "amount_text": "150rb"}],
    "_raw": "21 sep serviced Mr Budi living room AC, refilled freon 150rb",
}
split_plan = parse.plan(split, {"people": {}}, TODAY, lang_code="en")
check("satu kerjaan tidak jadi dua catatan, yang kosong dibuang",
      [e["kind"] for e in split_plan["entries"] if e["kind"] != "followup"], ["job"])
check("nominalnya tetap terbaca",
      [e["amount"] for e in split_plan["entries"] if e["kind"] == "job"], [150000])

two = dict(split, date_in_days=None,
           items=[{"kind": "job", "amount_text": "150rb"},
                  {"kind": "job", "amount_text": "200rb"}])
two_plan = parse.plan(two, {"people": {}}, TODAY, lang_code="en")
check("dua angka kerjaan tidak ditebak diam-diam", two_plan["action"], "confirm")
check("dua angka ditanya dengan menyebut keduanya",
      "150rb" in two_plan["question"] and "200rb" in two_plan["question"], True)

ghost = {
    "intent": "log", "person": "श्री सरी", "subject": "एसी", "subject_type": "ac_unit",
    "job_type": "servis", "date_text": "21 सितम्बर", "date_in_days": None,
    "followup_after_days": 90,
    "items": [{"kind": "job", "amount_text": "150rb"},
              {"kind": "promise", "when_text": None, "amount_text": None}],
    "_raw": "21 सितम्बर श्री सरी का एसी सर्विस, 150rb, बाकी है, अगले 3 महीने",
}
ghost_plan = parse.plan(ghost, {"people": {}}, TODAY, lang_code="en")
check("janji kosong dibuang, interval eksplisit tetap membuat follow-up",
      [e["kind"] for e in ghost_plan["entries"]], ["job", "followup"])

paid_unnamed = {
    "intent": "log", "person": "pak asep", "subject": None, "subject_type": "ac_unit",
    "job_type": "servis", "date_text": None, "date_in_days": None,
    "followup_after_days": None,
    "items": [{"kind": "job", "amount_text": "250rb"},
              {"kind": "payment", "amount_text": None}],
    "_raw": "pak asep ngutang 250rb, dia udah bayar sebagian",
}
unnamed = parse.plan(paid_unnamed, {"people": {}}, TODAY, lang_code="id")
check("bayar tanpa angka ditanya, bukan dicatat 0", unnamed["action"], "confirm")
check("pertanyaannya dalam bahasa pack", unnamed["question"], "Dia bayar berapa?")
check("yang ditanya item pembayarannya, bukan kerjaannya", unnamed["index"], 1)

# --- describe(), the sentence the worker actually reads ---------------------

import server  # noqa: E402

full = parse.plan({
    "intent": "log", "person": "pak asep", "subject": "AC ruang tamu",
    "subject_type": "ac_unit", "job_type": "servis", "date_text": "hari ini",
    "date_in_days": 0, "followup_after_days": None,
    "items": [{"kind": "job", "amount_text": "250rb"},
              {"kind": "payment", "amount_text": "100"}],
    "_raw": "pak asep ngutang total biaya service 250rb dia baru bayar 100",
}, {"people": {}}, TODAY, lang_code="id")

check("ringkasan indonesia menyebut sisa utang tanpa janji offer-again otomatis",
      server.describe(full, "id"),
      "Tercatat: Pak Asep, AC ruang tamu 250rb. Bayar 100rb, sisa utang 150rb "
      "(angka 100 gw baca sebagai ribuan, sama seperti angka lain di pesan itu).")
check("ringkasan inggris untuk pack yang sama tanpa follow-up otomatis",
      server.describe(full, "en"),
      "Noted: Pak Asep, AC ruang tamu 250k. Paid 100k, 150k still owed "
      "(I read 100 as thousands, same as the other number in that message).")

# Money handed over with no job behind it. This used to read "sisa utang -150rb",
# which is a debt with a minus sign in front of it: the worker has to decode the
# sentence to find out they were paid.
paid_only = {"action": "commit", "person": "pak_budi", "name": "Pak Budi",
             "person_raw": "pak_budi", "person_is_new": False, "subject": "",
             "subject_is_new": False, "subject_label": None, "subject_type": None,
             "text": "dia bayar", "currency": "IDR", "assumed_thousands": [],
             "rounded_cents": [],
             "entries": [{"kind": "job", "amount": 0,
                          "when": datetime(2026, 9, 24, 10, 0, 0)},
                         {"kind": "pay", "amount": 150000,
                          "when": datetime(2026, 9, 24, 10, 0, 0)}]}
check("bayar tanpa kerjaan bukan utang minus",
      server.describe(paid_only, "id", "IDR"),
      "Tercatat: Pak Budi, kerjaan. Bayar 150rb, kelebihan bayar 150rb.")
paid_usd = dict(paid_only, currency="USD",
                entries=[{"kind": "job", "amount": 150,
                          "when": datetime(2026, 9, 24, 10, 0, 0)},
                         {"kind": "pay", "amount": 150,
                          "when": datetime(2026, 9, 24, 10, 0, 0)}])
check("utang nol berarti lunas, bukan utang 0",
      server.describe(paid_usd, "en", "USD"),
      "Noted: Pak Budi, kerjaan $150. Paid $150, settled.")
paid_owed = dict(paid_usd, entries=[{"kind": "job", "amount": 150,
                                     "when": datetime(2026, 9, 24, 10, 0, 0)},
                                    {"kind": "pay", "amount": 50,
                                     "when": datetime(2026, 9, 24, 10, 0, 0)}])
check("masih kurang tetap ditulis kurang",
      server.describe(paid_owed, "en", "USD"),
      "Noted: Pak Budi, kerjaan $150. Paid $50, $100 still owed.")

check("kunci pack lama tetap kebaca indonesia",
      packlib.fold(["pack ac #k:pack #pk:abcd #pb:ac_service #at:2026-09-01T09:00:00"])["pack"]["lang"],
      "id")
check("kunci pack baru bawa bahasanya",
      packlib.fold(["pack ac #k:pack #pk:abcd #pb:ac_service #lang:en "
                    "#at:2026-09-01T09:00:00"])["pack"]["lang"], "en")
check("bahasa lain ikut tersimpan namanya",
      packlib.fold(["pack ac #k:pack #pk:abcd #lang:xx #ln:Espanol "
                    "#at:2026-09-01T09:00:00"])["pack"]["lang_name"], "Espanol")

# --- nama: yang mirip dan yang cuma kelihatan mirip -------------------------

check("pak yudi bukan pak budi",
      parse.resolve_person("pak yudi", {"pak_budi": {"name": "Pak Budi", "slug": "pak_budi",
                                                     "aliases": []}})[1], False)
check("dan hasilnya orang baru bernama pak yudi",
      parse.resolve_person("pak yudi", {"pak_budi": {"name": "Pak Budi", "slug": "pak_budi",
                                                     "aliases": []}})[0], "pak_yudi")
check("budi tetap pak budi",
      parse.resolve_person("budi", {"pak_budi": {"name": "Pak Budi", "slug": "pak_budi",
                                                 "aliases": []}})[0], "pak_budi")
check("pak budi tetap pak budi",
      parse.resolve_person("pak budi", {"pak_budi": {"name": "Pak Budi", "slug": "pak_budi",
                                                     "aliases": []}})[0], "pak_budi")
check("nama yang benar-benar beda lewat saja",
      parse.resolve_person("pak sari", {"pak_budi": {"name": "Pak Budi", "slug": "pak_budi",
                                                     "aliases": []}})[0], "pak_sari")
check("ibu sari dan pak sari tetap beda orang kalau dua-duanya ada",
      parse.resolve_person("bu sari", {"ibu_sari": {"name": "Ibu Sari", "slug": "ibu_sari",
                                                    "aliases": []}})[0], "ibu_sari")

# --- jawaban yang bukan nama tidak boleh jadi nama --------------------------

check("nama biasa diterima sebagai nama", server.looks_like_name("pak yudi"), True)
check("nama pendek diterima", server.looks_like_name("Budi"), True)
check("pertanyaan bukan nama", server.looks_like_name("pak yudi utang berapa?"), False)
check("angka bukan nama", server.looks_like_name("150"), False)
check("kalimat panjang bukan nama",
      server.looks_like_name("servis AC pak rizky 180rb belum lunas"), False)
check("kata tanya saja bukan nama", server.looks_like_name("berapa"), False)
check("kosong bukan nama", server.looks_like_name("   "), False)

pending = {"intent": "log", "person": "pak yudi", "subject": None, "subject_type": "ac_unit",
           "job_type": "servis", "date_text": None, "date_in_days": None,
           "followup_after_days": None,
           "items": [{"kind": "job", "amount_text": "220rb"}], "_raw": "servis pak yudi 220rb"}
check("pertanyaan yang datang saat ditanya nama tidak masuk jadi nama",
      server.patch_proposal(dict(pending, person=None), "person",
                            "pak yudi utang berapa?"), None)
check("nama sungguhan tetap masuk",
      server.patch_proposal(dict(pending, person=None), "person", "pak yudi")["person"],
      "pak yudi")
check("jawaban yang bukan angka tidak dipakai sebagai angka",
      server.patch_proposal(dict(pending, items=[{"kind": "job", "amount_text": None}]),
                            "amount", "pak yudi utang berapa?"), None)
check("angka tetap dipakai sebagai angka",
      server.patch_proposal(dict(pending, items=[{"kind": "job", "amount_text": None}]),
                            "amount", "220rb")["items"][0]["amount_text"], "220rb")
check("angka di item yang benar, bukan item pertama",
      server.patch_proposal({"items": [{"kind": "job", "amount_text": "250rb"},
                                       {"kind": "payment", "amount_text": None}]},
                            "amount", "100rb", 1)["items"],
      [{"kind": "job", "amount_text": "250rb"},
       {"kind": "payment", "amount_text": "100rb"}])

# --- halaman web: kata yang tampil harus datang dari bundel bahasa -----------
# Tes ini ada karena satu bug: pilihan jenis usaha ditulis langsung di HTML,
# jadi halaman berbahasa Inggris tetap menawarkan "Servis AC" dan "Bengkel".
# Membandingkan halaman dengan bundel bahasa menangkap seluruh kelas bug itu,
# bukan cuma satu kemunculan.

import re

HERE = os.path.dirname(os.path.abspath(__file__))
bundle_id = lang.ui_bundle("id")
bundle_en = lang.ui_bundle("en")

check("tabel id dan en punya kunci yang sama",
      sorted(set(bundle_id) - set(bundle_en)), [])
check("tabel en dan id punya kunci yang sama",
      sorted(set(bundle_en) - set(bundle_id)), [])

for _name in ("index.html", "home.html"):
    with open(os.path.join(HERE, "web", _name), encoding="utf-8") as _fh:
        _html = _fh.read()
    _keys = set(re.findall(r'data-i18n(?:-ph)?="([a-z0-9_]+)"', _html))
    check("%s: kunci ada di bundel indonesia" % _name,
          sorted(k for k in _keys if k not in bundle_id), [])
    check("%s: kunci ada di bundel inggris" % _name,
          sorted(k for k in _keys if k not in bundle_en), [])
    # Teks yang ditulis di dalam tag adalah teks yang tidak ikut bahasa apa pun.
    _written = [t.strip() for t in re.findall(r"<option\b[^>]*>([^<]*)</option>", _html)
                if t.strip()]
    check("%s: tidak ada pilihan yang ditulis langsung di HTML" % _name, _written, [])

with open(os.path.join(HERE, "web", "index.html"), encoding="utf-8") as _fh:
    _onboarding = _fh.read()
check("kartu Telegram muncul sesudah buat buku",
      'const card = $("telegramLinkCard")' in _onboarding, True)
check("kartu Telegram punya deep link bot",
      'href="https://t.me/memorandachatbot"' in _onboarding, True)
check("link bot menyalin key buku untuk ditempel",
      'navigator.clipboard.writeText(KEY)' in _onboarding, True)
check("tidak menampilkan tombol cek koneksi yang belum bekerja",
      'id="telegramCheckBtn"' in _onboarding, False)

with open(os.path.join(HERE, "web", "index.html"), encoding="utf-8") as _fh:
    _index = _fh.read()
check("pintu bahasa bebas sudah dilepas", 'data-pick="other"' in _index, False)
check("dua bahasa saja yang ditawarkan",
      sorted(re.findall(r'data-pick="([a-z]+)"', _index)), ["en", "id"])
# The money is asked once, at the moment the book is made, and can still be
# changed afterwards. Both doors have to exist or the setting is a dead end.
check("uang ditanya sekali pas bikin buku", 'id="curIn"' in _index, True)
check("uang bisa diganti di dalam buku", 'id="curSet"' in _index, True)
check("angka di halaman ikut setelan uang",
      'CUR === "USD" ? "$" + body : body' in _index, True)

# The new-book form used to sit in the same flex row as everything else, so the
# shop-name box came out 26px wide with a paragraph beside it at 495px. Anything
# that puts it back in a row is the bug returning.
check("form bikin buku bertumpuk, bukan satu baris",
      'id="createForm" class="stack"' in _index, True)
check("dan aturannya ada", "form.stack{display:block}" in _index, True)
check("tiap field bikin buku punya label",
      sorted(re.findall(r'<label for="(\w+)"', _index)), ["bizIn", "curIn", "nameIn", "tzFirstSet"])

# Jenis usaha yang sama, dua bahasa berbeda. Ini yang dulu sama persis.
for _biz, _key in (("Servis AC", "ui_biz_ac_service"), ("Bengkel", "ui_biz_workshop"),
                   ("Jahit", "ui_biz_tailor"), ("Usaha lain", "ui_biz_generic")):
    check("jenis usaha %s ikut bahasa" % _key,
          bundle_id[_key] == bundle_en[_key], False)
    check("jenis usaha %s indonesia" % _key, bundle_id[_key], _biz)

# Nama orang ditulis di tag sebagai slug, dan slug itu huruf kecil semua, jadi
# "Mr. John" tersimpan jadi "mr john" dan tidak ada cara mengembalikannya saat
# membaca. Kuncinya (#p:) tetap slug; yang dibaca orang tetap huruf aslinya.
check("nama ditulis apa adanya, bukan di-slug", packlib.name_tag("Mr. John"),
      "Mr._John")
check("spasi jadi garis bawah karena tag tidak boleh ada spasi",
      " " in packlib.name_tag("Mr. John"), False)
check("kunci orang tetap slug", packlib.slug("Mr. John"), "mr_john")
check("dan tetap orang yang sama saat dicari",
      packlib.slug("Mr. John") == packlib.slug("mr john"), True)
_named = {"intent": "log", "person": "Mr. John", "subject": "AC",
          "subject_type": "ac_unit", "job_type": "refill", "date_text": None,
          "date_in_days": None, "followup_after_days": None,
          "items": [{"kind": "job", "amount_text": "150$"}],
          "_raw": "Repaired Mr. John AC, cost 150$"}
_lines_named = parse.lines_for(
    parse.plan(_named, {"people": {}}, TODAY, lang_code="en"), lang_code="en")
check("baris orang bawa huruf aslinya, bukan huruf kecil semua",
      [packlib.tags_of(l).get("name") for l in _lines_named
       if packlib.kind_of(l) == "person"], ["Mr._John"])
check("dan yang tersimpan itu tetap kebaca sebagai namanya",
      packlib.fold(_lines_named)["people"]["mr_john"]["name"], "Mr. John")

# Pengingat yang isinya cuma tanggal bikin orang nanya "kok ini ada". Yang bikin
# jelas itu jaraknya dan kerjaan yang melahirkannya.
#
# Dibangun lewat fold atas baris sungguhan, bukan state bikinan: versi pertama
# tes ini memakai state buatan yang punya field yang cuma ditambahkan view, jadi
# lolos di tes dan kosong di semua pack sungguhan.
_rem_state = packlib.fold(_lines_named + [
    "collect what is still owed #k:rem #p:mr_john #s:ac #at:2026-09-27T10:00:00 "
    "#fire:2026-09-28T09:00:00 #kind:collect",
    "follow up with AC #k:rem #p:mr_john #s:ac #at:2026-09-27T10:00:01 "
    "#fire:2026-12-26T09:00:00 #kind:follow_up",
])
_rem_state["pack"] = {"currency": "USD"}
_rems = server.reminder_view(_rem_state, "en")
check("yang paling dekat tampil paling depan", _rems[0]["kind"], "collect")
check("namanya huruf aslinya, bukan slug",
      sorted({r["person"] for r in _rems}), ["Mr. John"])
check("tiap pengingat jauh bawak jaraknya, bukan cuma tanggal",
      all(re.match(r"^in \d+ days$", r["when"]) for r in _rems if r["kind"] == "follow_up"),
      True)
check("dan menyebut kerjaan asalnya",
      [r["from"] for r in _rems if r["kind"] == "follow_up"],
      ["from the %s job" % lang.short_date(
          datetime.strptime(sorted(j["when"] for j in _rem_state["jobs"].values())[0],
                            "%Y-%m-%d"), "en")])
# Kata-katanya diuji langsung dengan angka, supaya tesnya gak berubah arti besok
# pagi cuma karena harinya berganti.
check("yang udah lewat bilang telat", server._distance(-3, "en"), "3 days late")
check("besok ditulis besok", server._distance(1, "id"), "besok")
check("hari ini ditulis hari ini", server._distance(0, "id"), "hari ini")
check("90 hari ditulis 90 hari", server._distance(90, "en"), "in 90 days")
check("inggris tidak lagi bilang 'offer again AC'",
      lang.t("en", "line_offer_again", "AC"), "offer the AC job again")

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all language tests passed")
