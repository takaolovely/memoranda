#!/usr/bin/env python3
"""Offline tests. No network, no credentials, no model.

The point of these is that everything the money depends on is arithmetic that
can be checked here, rather than a sentence a model produced.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import packlib  # noqa: E402
import parse  # noqa: E402

FAILED = []


def check(name, got, want):
    if got == want:
        print("ok   %s" % name)
    else:
        print("FAIL %s\n       got  %r\n       want %r" % (name, got, want))
        FAILED.append(name)


# --- money -----------------------------------------------------------------

check("150 tanpa satuan itu ambigu", parse.amount_of("150"), (None, True))
check("150rb", parse.amount_of("150rb"), (150000, False))
check("150 k", parse.amount_of("150 k"), (150000, False))
check("150.000", parse.amount_of("150.000"), (150000, False))
check("150000", parse.amount_of("150000"), (150000, False))
check("1,5jt", parse.amount_of("1,5jt"), (1500000, False))
check("2 juta", parse.amount_of("2 juta"), (2000000, False))
check("seratus lima puluh ribu", parse.amount_of("seratus lima puluh ribu"), (150000, False))
check("tanpa angka", parse.amount_of("gak nyebut"), (None, True))
check("angka besar tanpa satuan lolos", parse.amount_of("150000 dibayar"), (150000, False))

# --- money, when the currency is known -------------------------------------
# Reported from a live book: "Repaired Mr. John AC, cost 150$ Paid" was answered
# with "150 thousand or 150?", and answering "150$" got the same question again.
# The book was arguing with somebody who had already written the dollar sign.

check("$150 bukan pertanyaan", parse.amount_of("150$"), (150, False))
check("$ di depan juga", parse.amount_of("$150"), (150, False))
check("$ menang atas setelan rupiah",
      parse.amount_of("$150", currency="IDR"), (150, False))
check("usd 150 menulis kata dollar",
      parse.amount_of("cost 150 usd"), (150, False))
check("150 thousand itu seratus lima puluh ribu",
      parse.amount_of("150 thousand"), (150000, False))
check("dollar: angka telanjang bukan pertanyaan",
      parse.amount_of("150", currency="USD"), (150, False))
check("dollar: 1.5 juta lewat kata",
      parse.amount_of("1.5 million", currency="USD"), (1500000, False))
check("dollar: 12.50 itu dua belas dolar, bukan 1250",
      parse.amount_of("$12.50"), (13, False))
check("dollar: 1,500 tetap seribu lima ratus",
      parse.amount_of("$1,500"), (1500, False))
check("rupiah tidak berubah sedikit pun",
      parse.amount_of("150.000", currency="IDR"), (150000, False))
check("rp menang atas setelan dolar",
      parse.amount_of("150rb", currency="USD"), (150000, False))
check("dua mata uang sekaligus tidak diputuskan di sini",
      parse.marked_currency("$100 dan Rp 100"), None)
check("sennya dilaporkan, bukan dibuang diam-diam",
      parse._read_amount("$12.50", "USD")[2], True)
check("rupiah tidak pernah melaporkan sen",
      parse._read_amount("150.000", "IDR")[2], False)

# The question offers both readings, so the answer has to be accepted. Answering
# "150" to "150 ribu atau 150?" used to get the same question back, which is a
# loop with no exit unless the worker happens to type "rb".
check("jawaban '150' dibaca apa adanya",
      parse._read_amount("150", "IDR", answered=True), (150, False, False))
check("jawaban '150' tidak ditanya lagi",
      parse._read_amount("150", "IDR", answered=False), (None, True, False))
check("jawaban '150rb' tetap seratus lima puluh ribu",
      parse._read_amount("150rb", "IDR", answered=True), (150000, False, False))

# A dollar sign inside a rupiah book is read as written and said out loud, not
# silently mixed. The ledger holds one number per entry and takes its unit from
# the book, so this is the one case where the reading is worth announcing.
_ringgit = parse.plan(
    {"intent": "log", "person": "Mr Budi", "subject": "AC", "subject_type": "ac_unit",
     "job_type": "servis", "date_text": "21 sep", "date_in_days": 0,
     "followup_after_days": None,
     "items": [{"kind": "job", "amount_text": "$150"}],
     "_raw": "serviced Mr Budi AC, cost $150"},
    {"people": {}, "currency": "IDR"}, datetime(2026, 9, 25, 10, 0, 0),
    lang_code="en")
check("dolar di buku rupiah tetap dibaca 150",
      [e["amount"] for e in _ringgit["entries"] if e["kind"] == "job"], [150])
check("dan itu dikatakan, bukan diam-diam",
      _ringgit["mixed_currency"], ["USD"])
_matching = parse.plan(
    {"intent": "log", "person": "Mr Budi", "subject": "AC", "subject_type": "ac_unit",
     "job_type": "servis", "date_text": "21 sep", "date_in_days": 0,
     "followup_after_days": None,
     "items": [{"kind": "job", "amount_text": "$150"}],
     "_raw": "serviced Mr Budi AC, cost $150"},
    {"people": {}, "currency": "USD"}, datetime(2026, 9, 25, 10, 0, 0),
    lang_code="en")
check("kalau uangnya cocok, tidak ada catatan apa-apa",
      _matching["mixed_currency"], [])

# --- dates -----------------------------------------------------------------

today = datetime(2026, 9, 25, 10, 0, 0)
check("21 sep", parse.resolve_date("21 sep", today)[0].strftime("%Y-%m-%d"), "2026-09-21")
check("kemarin", parse.resolve_date("kemarin", today)[0].strftime("%Y-%m-%d"), "2026-09-24")
check("hari ini", parse.resolve_date("hari ini", today)[0].strftime("%Y-%m-%d"), "2026-09-25")
check("desember tahun lalu", parse.resolve_date("3 des", today)[0].strftime("%Y-%m-%d"),
      "2025-12-03")

# --- lines -----------------------------------------------------------------

line = packlib.render("job", "Servis AC ruang tamu, isi freon",
                      p="pak_budi", s="ac_ruang_tamu", job="abc123",
                      type="refill", amount=150000, at=datetime(2026, 9, 21, 9, 0, 0))
check("kind terbaca", packlib.kind_of(line), "job")
check("body bersih", packlib.body_of(line), "Servis AC ruang tamu, isi freon")
junk = line + " #ngaco:yes"
check("tag asing inert", "ngaco" in packlib.tags_of(junk), False)
check("tag asli tetap ada", packlib.tags_of(junk).get("amount"), "150000")

check("job id sama untuk kalimat sama",
      packlib.job_id("pak_budi", "ac", "refill", datetime(2026, 9, 21), 150000),
      packlib.job_id("pak_budi", "ac", "refill", datetime(2026, 9, 21), 150000))

# --- fold ------------------------------------------------------------------

lines = [
    packlib.render("pack", "pack demo", pk="abcd1234", biz="Servis AC",
                   pb="ac_service", tz="Asia/Jakarta", at=datetime(2026, 9, 20)),
    packlib.render("person", "Pak Budi", p="pak_budi", name="Pak_Budi",
                   alias="pak_budi", at=datetime(2026, 9, 21, 9, 0, 0)),
    packlib.render("subject", "AC ruang tamu", p="pak_budi", s="ac_ruang_tamu",
                   type="ac_unit", loc="ruang_tamu", at=datetime(2026, 9, 21, 9, 0, 0)),
    packlib.render("job", "Servis AC ruang tamu, isi freon", p="pak_budi",
                   s="ac_ruang_tamu", job="j1", type="refill", amount=150000,
                   at=datetime(2026, 9, 21, 9, 0, 0)),
]
state = packlib.fold(lines)
check("saldo jadi 150rb", state["people"]["pak_budi"]["balance"], 150000)
check("subject kebaca", state["people"]["pak_budi"]["subjects"]["ac_ruang_tamu"]["label"],
      "AC ruang tamu")

state = packlib.fold(lines + [
    packlib.render("pay", "Budi bayar separuh", p="pak_budi", ref="j1",
                   amount=100000, at=datetime(2026, 9, 22, 9, 0, 0))])
check("bayar separuh mengurangi saldo", state["people"]["pak_budi"]["balance"], 50000)

state = packlib.fold(lines + [
    packlib.render("pay", "Budi bayar lunas", p="pak_budi", ref="j1", amount=150000,
                   at=datetime(2026, 9, 23, 9, 0, 0))])
check("bayar lunas jadi nol", state["people"]["pak_budi"]["balance"], 0)

state = packlib.fold(lines + [packlib.render("void", "salah catat", ref="j1",
                                             at=datetime(2026, 9, 24, 9, 0, 0))])
check("void membatalkan job", state["people"]["pak_budi"]["balance"], 0)

dup = packlib.fold(lines + [lines[3]])
check("baris kembar tidak menggandakan saldo",
      dup["people"]["pak_budi"]["balance"], 150000)

out_of_order = packlib.fold([lines[3], lines[0], lines[2], lines[1]])
check("urutan baca tidak mengubah hasil",
      out_of_order["people"]["pak_budi"]["balance"], 150000)

# --- the plan the code makes ----------------------------------------------

proposal = {
    "intent": "log", "person": "pak budi", "subject": "AC ruang tamu",
    "subject_type": "ac_unit", "job_type": "refill", "date_text": "21 sep",
    "items": [{"kind": "job", "amount_text": "150"}],
    "_raw": "21 sep servis AC pak budi ruang tamu isi freon 150 belum lunas",
}
plan = parse.plan(proposal, {"people": {}}, today)
check("angka tanpa satuan ditanya dulu", plan["action"], "confirm")
check("yang ditanya soal uang", plan.get("field"), "amount")

proposal["items"][0]["amount_text"] = "150rb"
proposal["followup_after_days"] = 90
plan = parse.plan(proposal, {"people": {}}, today)
check("setelah diperjelas langsung commit", plan["action"], "commit")
check("tanggal follow-up ikut diminta eksplisit", any(
    e["kind"] == "followup" and e["days"] == 90 for e in plan["entries"]), True)
check("nominal jadi rupiah", plan["entries"][0]["amount"], 150000)

made = parse.lines_for(plan)
check("baris yang ditulis", [packlib.kind_of(l) for l in made],
      ["person", "subject", "job", "rem"])
check("interval eksplisit 90 hari dari tanggal kerjaan, jam 9 pagi",
      [packlib.tags_of(l).get("fire") for l in made if packlib.kind_of(l) == "rem"],
      ["2026-12-20T09:00:00"])
check("tanpa interval eksplisit, tidak bikin follow-up otomatis",
      [packlib.tags_of(l).get("kind") for l in parse.lines_for(
          parse.plan({**proposal, "followup_after_days": None}, {"people": {}}, today))
       if packlib.kind_of(l) == "rem"], [])

# a second identical message must not double the debt
again = parse.lines_for(parse.plan(proposal, {"people": {}}, today))
check("kalimat kembar menghasilkan baris identik",
      [packlib.tags_of(l).get("job") for l in again if packlib.kind_of(l) == "job"],
      [packlib.tags_of(l).get("job") for l in made if packlib.kind_of(l) == "job"])

# --- the sentence that was recorded wrong on the live prototype ------------

multi = {
    "intent": "log", "person": "pak asep", "subject": "AC ruang tamu",
    "subject_type": "ac_unit", "job_type": "servis", "date_text": "hari ini",
    "items": [{"kind": "job", "amount_text": "250rb"},
              {"kind": "payment", "amount_text": "100", "when_text": None},
              {"kind": "promise", "when_text": "minggu depan", "amount_text": "100"}],
    "_raw": "pak asep ngutang total biaya service 250rb dia baru bayar 100 "
            "nanti dibayar minggu depan",
}
multi_plan = parse.plan(multi, {"people": {}}, today)
check("pesan tidak meminta follow-up ulang secara otomatis",
      [e["kind"] for e in multi_plan["entries"]],
      ["job", "pay", "promise"])
check("angka telanjang ikut skala pesannya, dan dicatat bahwa itu diasumsikan",
      multi_plan["assumed_thousands"], ["100"])
check("janji bayar bikin pengingat tagih tanpa offer-again otomatis",
      [packlib.tags_of(l).get("kind") for l in parse.lines_for(multi_plan)
       if packlib.kind_of(l) == "rem"], ["collect"])

multi_state = packlib.fold(parse.lines_for(multi_plan))
check("utang pak asep tinggal 150rb, bukan 250rb",
      multi_state["people"]["pak_asep"]["balance"], 150000)

tagihan = [r for r in multi_state["reminders"] if r["kind"] == "collect"]
check("pengingat tagih jatuh 7 hari dari sekarang", tagihan and tagihan[0]["fire"],
      (today + timedelta(days=7)).replace(hour=9, minute=0, second=0).strftime(packlib.STAMP))

# a bare number with nothing else to compare it to is still a question
alone = {"intent": "log", "person": "bu sari", "subject": None, "subject_type": None,
         "job_type": "servis", "date_text": "hari ini",
         "items": [{"kind": "job", "amount_text": "100"}], "_raw": "bu sari servis 100"}
check("angka telanjang tanpa pembanding tetap ditanya",
      parse.plan(alone, {"people": {}}, today)["action"], "confirm")

alone["items"][0]["amount_text"] = "100rb"
no_subject_plan = parse.plan(alone, {"people": {}}, today)
check("tanpa subject, tidak ada baris subject atau follow-up palsu",
      [packlib.kind_of(l) for l in parse.lines_for(no_subject_plan)],
      ["person", "job"])
check("subject kosong tetap tidak jadi slug x", no_subject_plan["subject"], "")

# --- names -----------------------------------------------------------------

known = {"pak_budi": {"slug": "pak_budi", "name": "pak budi",
                      "aliases": ["pak_budi"], "subjects": {}}}
check("budi = pak budi, tidak ditanya",
      parse.resolve_person("Budi", known)[:3], ("pak_budi", False, ""))
check("nama yang ditulis balik itu yang di berkas, bukan kalimatnya",
      parse.resolve_person("Budi", known)[3], "pak budi")
check("nama baru diterima",
      parse.resolve_person("Bu Sari", known)[0], "bu_sari")
two = dict(known)
two["budi_ac"] = {"slug": "budi_ac", "name": "Budi AC", "aliases": ["budi_ac"], "subjects": {}}
check("dua kandidat mirip -> ditanya", parse.resolve_person("Budi", two)[1], True)

pay_proposal = {"intent": "log", "person": "Budi", "subject": None, "subject_type": None,
                "job_type": None, "date_text": "hari ini",
                "items": [{"kind": "payment", "amount_text": "150rb", "when_text": None}],
                "_raw": "pak budi bayar 150rb"}
pay_plan = parse.plan(pay_proposal, {"people": known}, today)
check("bayar dengan nama pendek langsung commit", pay_plan["action"], "commit")
check("bayar masuk ke orang yang benar", pay_plan["person"], "pak_budi")
check("bayar dicatat sebagai pay", pay_plan["entries"][0]["kind"], "pay")

# --- satu pesan tidak boleh bertentangan ------------------------------------
# "servis 150rb bayar cash, 2 minggu lagi minta isiin freon" pernah tercatat
# lunas SEKALIGUS janji bayar 150rb tanggal 8 Okt. Yang 2 minggu itu bukan janji
# bayar, itu tugas. Kalau kerjaannya udah dibayar penuh, janji bayar mustahil.

def proposal_with(items, **extra):
    base = {"intent": "log", "person": "Pak Bobi", "subject": "AC",
            "subject_type": "ac_unit", "job_type": "servis", "date_text": None,
            "items": items, "_raw": "pesan mentah"}
    base.update(extra)
    return base


paid_items = [
    {"kind": "job", "amount_text": "150rb"},
    {"kind": "payment", "amount_text": "150rb", "when_text": None},
    {"kind": "promise", "when_text": "2 minggu lagi", "when_in_days": 14,
     "amount_text": "150rb"},
]
paid_plan = parse.plan(proposal_with(paid_items), {"people": {}}, today)
kinds = [e["kind"] for e in paid_plan["entries"]]
check("lunas + tanggal nyasar: janji bayar dibuang", "promise" in kinds, False)
check("lunas + tanggal nyasar: tanggalnya gak hilang", "task" in kinds, True)
task_when = [e["when"] for e in paid_plan["entries"] if e["kind"] == "task"][0]
check("lunas + tanggal nyasar: tanggalnya 2 minggu dari hari tes",
      task_when.strftime("%Y-%m-%d"), (today + timedelta(days=14)).strftime("%Y-%m-%d"))
check("lunas + tanggal nyasar: gak ada tagih di barisnya",
      [l for l in parse.lines_for(paid_plan) if "tagih" in l], [])
check("lunas + tanggal nyasar: ada ingetin di barisnya",
      any("ingetin" in l for l in parse.lines_for(paid_plan)), True)
check("job lunas tidak dapat follow-up otomatis",
      [e["kind"] for e in paid_plan["entries"]], ["job", "pay", "task"])

# Yang bener: pembaca ngirim task sendiri, jadi penjaganya gak perlu nebak.
task_items = [
    {"kind": "job", "amount_text": "150rb"},
    {"kind": "payment", "amount_text": "150rb"},
    {"kind": "task", "what_text": "minta isiin freon", "when_text": "2 minggu lagi",
     "when_in_days": 14},
]
task_plan = parse.plan(proposal_with(task_items), {"people": {}}, today)
task_entries = [e for e in task_plan["entries"] if e["kind"] == "task"]
check("task kebaca dari pembaca", len(task_entries), 1)
check("task nempel ke tanggal yang benar", task_entries[0]["when"],
      today + timedelta(days=14))
check("task nulis apa yang harus dikerjain", task_entries[0]["what"], "minta isiin freon")
check("task jadi baris ingetin",
      [l.split(" #")[0] for l in parse.lines_for(task_plan) if "#kind:task" in l],
      ["ingetin minta isiin freon"])

# Sisa utang beneran: janji bayar harus tetap ada, dan gak boleh lebih dari sisa.
partial = [
    {"kind": "job", "amount_text": "250rb"},
    {"kind": "payment", "amount_text": "100rb"},
    {"kind": "promise", "when_text": "minggu depan", "when_in_days": 7,
     "amount_text": "250rb"},
]
partial_plan = parse.plan(proposal_with(partial), {"people": {}}, today)
promise = [e for e in partial_plan["entries"] if e["kind"] == "promise"]
check("sisa 150rb: janji bayar tetap ada", len(promise), 1)
check("janji bayar dipotong sampai sisa utang saja", promise[0]["amount"], 150000)
check("sisa utang tetap ada tagih",
      [l.split(" #")[0] for l in parse.lines_for(partial_plan) if "#kind:collect" in l],
      ["tagih 150rb"])

# Pesan yang cuma janji bayar (kerjaannya dari pesan lama) jangan ikut dibuang.
only_promise = [{"kind": "promise", "when_text": "minggu depan", "when_in_days": 7,
                 "amount_text": "100rb"}]
op_plan = parse.plan(proposal_with(only_promise), {"people": {}}, today)
check("pesan janji bayar tanpa kerjaan tetap lolos",
      [e["kind"] for e in op_plan["entries"]], ["promise"])

# Task tanpa isi bukan task.
empty_task = [{"kind": "job", "amount_text": "150rb"},
              {"kind": "task", "what_text": "  ", "when_in_days": 14}]
et_plan = parse.plan(proposal_with(empty_task), {"people": {}}, today)
check("task kosong dibuang", [e["kind"] for e in et_plan["entries"]], ["job"])

# Pesan yang cuma minta diingetin: gak ada duit di dalamnya, jadi jangan ditanya
# nominal. Dulu ini minta "Nominalnya berapa?" buat sebuah pengingat.
only_task = [{"kind": "task", "what_text": "minta isiin freon", "when_in_days": 14}]
ot_plan = parse.plan(proposal_with(only_task), {"people": {}}, today)
check("pesan cuma reminder gak ditanya nominal", ot_plan["action"], "commit")
check("pesan cuma reminder jadi satu task",
      [e["kind"] for e in ot_plan["entries"]], ["task"])

# Explicit clock times must survive normalization and ledger rendering. Before
# this regression, every promise/task reminder was forced to 09:00 regardless of
# what the user typed, so alarms fired shortly after creation.
for raw, expected in (("remind me tomorrow at 9pm", "21:00:00"),
                      ("remind me at 7:30 AM", "07:30:00"),
                      ("besok jam 6 pagi", "06:00:00"),
                      ("malam ini pukul 8 malam", "20:00:00")):
    clock = parse.explicit_clock(raw)
    check("jam eksplisit terbaca: " + raw,
          "%02d:%02d:00" % clock if clock else None, expected)

clock_proposal = proposal_with(
    [{"kind": "task", "what_text": "call the customer", "when_text": "tomorrow",
      "when_in_days": 1}],
    _raw="Remind me to call the customer tomorrow at 9 PM")
clock_plan = parse.plan(clock_proposal, {"people": {}, "timezone": "Asia/Jakarta"},
                        datetime(2026, 9, 29, 13, 0), lang_code="en")
clock_line = next(line for line in parse.lines_for(clock_plan, "en")
                  if "#kind:task" in line)
check("jam reminder 9pm tersimpan, bukan 9am",
      packlib.tags_of(clock_line).get("fire"), "2026-09-30T21:00:00")

promise_proposal = proposal_with(
    [{"kind": "promise", "when_text": "tomorrow", "when_in_days": 1,
      "amount_text": "50"}],
    _raw="Mr Bob will pay the remaining $50 tomorrow at 8pm")
promise_plan = parse.plan(promise_proposal, {"people": {}},
                          datetime(2026, 9, 29, 13, 0), lang_code="en", currency="USD")
promise_line = next(line for line in parse.lines_for(promise_plan, "en")
                    if "#kind:collect" in line)
check("jam janji bayar 8pm tersimpan",
      packlib.tags_of(promise_line).get("fire"), "2026-09-30T20:00:00")

default_clock_plan = parse.plan(
    proposal_with([{"kind": "task", "what_text": "call", "when_in_days": 1}],
                  _raw="remind me tomorrow to call"),
    {"people": {}, "timezone": "Asia/Jakarta"}, datetime(2026, 9, 29, 13, 0), lang_code="en")
default_clock_line = next(line for line in parse.lines_for(default_clock_plan, "en")
                          if "#kind:task" in line)
check("default reminder tanpa jam tetap 9am",
      packlib.tags_of(default_clock_line).get("fire"), "2026-09-30T09:00:00")

# --- reminder dihitung dari keadaan, bukan dari barisnya --------------------
# Baris "tagih sisa utang" pernah mendarat di Walrus untuk orang yang sudah
# lunas. Walrus tidak bisa diedit, jadi satu-satunya cara benerin baris begitu
# adalah memutuskan ulang tiap kali dari saldo.

def pack_lines(job, pay, extras):
    out = ['pak bobi #k:person #p:pak_bobi #name:pak_bobi #alias:pak_bobi '
           '#at:2026-09-25T10:00:00',
           'pak bobi servis ac #k:job #p:pak_bobi #s:ac #type:servis #job:abc '
           '#amount:%d #at:2026-09-25T10:00:00' % job]
    if pay:
        out.append('bayar #k:pay #p:pak_bobi #amount:%d #at:2026-09-25T10:00:00 '
                   '#ref:abc' % pay)
    return out + extras


tagih = ('tagih sisa utang #k:rem #p:pak_bobi #s:ac #at:2026-09-25T10:00:00 '
         '#fire:2026-10-09T09:00:00 #kind:collect')
tawarin = ('tawarin lagi ac #k:rem #p:pak_bobi #s:ac #at:2026-09-25T10:00:00 '
           '#fire:2026-12-24T09:00:00 #kind:follow_up')
ingetin = ('ingetin minta isiin freon #k:rem #p:pak_bobi #s:ac '
           '#at:2026-09-25T10:00:00 #fire:2026-10-09T09:00:00 #kind:task')

lunas_state = packlib.fold(pack_lines(150000, 150000, [tagih, tawarin, ingetin]))
check("lunas: baris tagih tetap ada di Walrus",
      sorted(r["kind"] for r in lunas_state["reminders"]),
      ["collect", "follow_up", "task"])
check("lunas: tagih disembunyikan, tawarin dan ingetin tetap tampil",
      sorted(r["kind"] for r in packlib.live_reminders(lunas_state)),
      ["follow_up", "task"])

utang_state = packlib.fold(pack_lines(250000, 100000, [tagih, tawarin]))
check("masih utang 150rb: tagih tetap tampil",
      sorted(r["kind"] for r in packlib.live_reminders(utang_state)),
      ["collect", "follow_up"])

check("reminder orang yang gak dikenal disembunyikan",
      packlib.live_reminders(packlib.fold(
          ['tagih sisa utang #k:rem #p:orang_hilang #fire:2026-10-09T09:00:00 '
           '#kind:collect'])), [])

print()
print("%d failed" % len(FAILED) if FAILED else "all tests passed")
sys.exit(1 if FAILED else 0)
