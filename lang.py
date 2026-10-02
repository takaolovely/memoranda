"""Language is a setting on the pack, not a guess the model makes.

The probe that produced this file is worth reading before changing anything here.
Given an Indonesian-only prompt and English input, the model read the sentence
perfectly (right person, right amount, right interval) and then answered in
Indonesian anyway. Given Spanish input, same thing. So the model is good at
understanding any language and bad at being told which one to speak in.

That splits the job in two, and the split is the whole design:

  * words the code writes (every confirmation, every question, every button) come
    from the table below. No model, no drift, exact in every language.
  * the one free sentence the model writes (the answer to a question) is asked
    for in the pack language and then CHECKED by the code, because asking is not
    a guarantee.

The check is offline and cheap: a script test where the language has its own
alphabet, and a function-word score where it does not. It only flags a mismatch
it is confident about, since a retry costs a call and a false alarm costs trust.
"""

import re
import unicodedata

DEFAULT_LANG = "id"

DEFAULT_CURRENCY = "IDR"

# The market a language is read in. This is only the starting point for a new
# book, never a rule about the speaker: somebody in Jakarta who switches the page
# to English still pays in rupiah, so the money setting is separate from the
# language setting and a language change does not re-price a book.
CURRENCY_FOR_LANG = {"id": "IDR", "en": "USD"}

CURRENCY_NAMES = {"IDR": "Rupiah", "USD": "US dollar"}

CURRENCY_ALIASES = {
    "idr": "IDR", "rp": "IDR", "rupiah": "IDR", "indonesia": "IDR",
    "usd": "USD", "us$": "USD", "dollar": "USD", "dollars": "USD", "us dollar": "USD",
}


def resolve_currency(value, lang_code=DEFAULT_LANG):
    """A typed currency becomes a code, and an empty one falls back to the
    language's market."""
    raw = " ".join(str(value or "").lower().split())
    if not raw:
        return currency_for(lang_code)
    return CURRENCY_ALIASES.get(raw, raw.upper())


def currency_for(lang_code):
    """The currency a new book starts in when it speaks this language."""
    return CURRENCY_FOR_LANG.get(lang_code or DEFAULT_LANG, DEFAULT_CURRENCY)


def currency_name(code):
    return CURRENCY_NAMES.get(code or "", code or "")

# One place the product name is written down. The pages read it from the i18n
# bundle, so renaming the product is a one-line change and not a hunt through
# templates.
BRAND = "Memoranda"

# The two we can write by hand, plus anything else the person types. A pack in a
# language we have no table for gets English buttons and a locked model, which is
# honest: the words the code writes are correct-ish, the words the model writes
# are verified by script or left unchecked and flagged.
HAND_WRITTEN = ("id", "en")

NAMES = {"id": "Indonesian", "en": "English"}
SELF_NAMES = {"id": "Bahasa Indonesia", "en": "English"}

ALIASES = {
    "indonesian": "id", "indonesia": "id", "bahasa": "id", "bahasa indonesia": "id",
    "id": "id", "indo": "id",
    "english": "en", "inggris": "en", "en": "en", "eng": "en",
}


def resolve_lang(value):
    """A typed language becomes a code we know, or a name we pass through.

    Returns (code, display name). Unknown languages keep their own spelling:
    the prompt gets that name and the model is told to answer only in it.
    """
    raw = str(value or "").strip()
    if not raw:
        return DEFAULT_LANG, SELF_NAMES[DEFAULT_LANG]
    key = raw.lower()
    if key in ALIASES:
        code = ALIASES[key]
        return code, SELF_NAMES[code]
    clean = " ".join(raw.split())[:24]
    return "xx", clean


def prompt_name(lang, name=""):
    """What to call this language when talking to the model."""
    if lang in NAMES:
        return NAMES[lang]
    return str(name or "").strip() or "the language the worker used"


# ---------------------------------------------------------------------------
# what the code says, per language
# ---------------------------------------------------------------------------

STRINGS = {
    "id": {
        "ask_person": "Nama pelanggannya siapa?",
        "ask_person_again": "Nama pelanggannya siapa? Tulis ulang dengan namanya.",
        "ask_person_clash": "Maksudnya %s, atau orang baru?",
        "ask_amount_bare": "Angkanya %s. Maksudnya %s ribu atau %s rupiah?",
        "ask_two_amounts": "Ada dua angka di pesan itu (%s). Satu kerjaan satu catatan ya, kirim ulang satu-satu.",
        "ask_paid_amount": "Dia bayar berapa?",
        "ask_amount": "Nominalnya berapa?",
        "ask_what": "Mau dicatat apa?",
        "confirm_default": "Konfirmasi dulu ya.",
        "recap_head": "Tercatat: %s",
        "recap_job": "%s %s",
        "recap_job_no_amount": "%s",
        "recap_pay": "Bayar %s",
        "recap_left": "sisa utang %s",
        "recap_promise": "Janji bayar %s, gw ingetin",
        "recap_followup": "Gw ingetin nawarin lagi %s hari lagi (%s)",
        "recap_assumed": "(angka %s gw baca sebagai ribuan, sama seperti angka lain di pesan itu)",
        "recap_rounded": "(angka %s ada sennya, gw bulatin ke satuan terdekat)",
        "recap_mixed_currency": "(kamu nulis %s di buku %s, angka itu gw baca apa adanya)",
        "recap_queued": "(catatan masih di antrean kirim, ke limit relayer%s)",
        "recap_queued_wait": ", tunggu %d detik",
        "unknown_key": "kunci tidak dikenal",
        "not_understood": "belum paham",
        "line_pay": "bayar %s",
        "line_collect": "tagih %s",
        "line_collect_left": "tagih sisa utang",
        "line_offer_again": "tawarin lagi %s",
        "line_remind": "ingetin %s",
        "line_remind_generic": "ingetin %s",
        "line_alias": "nama lain: %s",
        # Jarak pengingat, ditulis relatif. Tanggal sendirian bikin orang nanya
        # "kok ini muncul" - yang bikin jelas itu berapa lama lagi, bukan
        # tanggalnya.
        "rem_today": "hari ini",
        "rem_tomorrow": "besok",
        "rem_in_days": "%d hari lagi",
        "rem_late": "telat %d hari",
        "rem_from": "dari kerjaan %s",
        "line_pack": "pack %s",
        "ui_pick_lang": "Pilih bahasa",
        "ui_pick_lang_note": "Bahasa ini dipakai seterusnya buat pack ini. Bisa diganti kapan aja di setelan.",
        "ui_pick_cur": "Uangnya rupiah atau dolar?",
        "ui_pick_cur_note": "Sekali jawab, gak ditanya lagi. Orang nulis \"150\" artinya beda: 150 ribu kalau rupiah, 150 dolar kalau dolar. Kalau pesanmu udah nulis $ atau Rp sendiri, itu yang menang.",
        "ui_cur_idr": "Rupiah (Rp)",
        "ui_cur_usd": "USD ($)",
        "ui_cur_label": "Uang",
        "ui_change_cur": "Ganti uang",
        "ui_timezone": "Zona waktu",
        "ui_change_timezone": "Ganti zona waktu",
        "ui_timezone_note": "Pengingat baru memakai zona waktu buku saat ini.",
        "ui_tz_jakarta": "WIB (Jakarta)",
        "ui_tz_makassar": "WITA (Makassar)",
        "ui_tz_jayapura": "WIT (Jayapura)",
        "ui_tz_singapore": "Singapura",
        "ui_tz_bangkok": "Bangkok",
        "ui_tz_utc": "UTC",
        "ui_tz_london": "London",
        "ui_tz_new_york": "New York",
        "ui_tz_los_angeles": "Los Angeles",
        "ui_tz_saved": "Zona waktu diubah ke %s.",
        "ui_tz_confirm_title": "Zona waktu untuk pengingat",
        "ui_tz_confirm_note": "Pengingat bertanggal pertama akan mengikuti zona ini. Bisa diganti nanti di setelan.",
        "ui_tz_error": "Zona waktu tidak berhasil diubah.",
        "ui_cur_now": "Uangnya sekarang %s. Angka telanjang dibaca sesuai itu.",
        # Jenis usaha. Dulu ini ditulis langsung di HTML, jadi halaman Inggris
        # tetap menawarkan "Servis AC" dan "Bengkel".
        "ui_biz_ac_service": "Servis AC",
        "ui_biz_workshop": "Bengkel",
        "ui_biz_tailor": "Jahit",
        "ui_biz_generic": "Usaha lain",
        "ui_key_ph": "tempel kunci di sini",
        "ui_open": "Buka",
        "ui_new_ph": "contoh: Prima Jaya",
        "ui_pick_biz": "Jenis usaha",
        "ui_pick_name": "Nama toko (opsional)",
        "ui_or_new": "atau bikin buku baru",
        "ui_new": "Bikin baru",
        "ui_say_ph": "mis. 21 sep servis AC pak budi ruang tamu isi freon 150 belum lunas next 3 bulan",
        "ui_send": "Kirim",
        "ui_copy": "Copy kunci",
        "ui_refresh": "Muat ulang",
        "ui_people": "Orang",
        "ui_reminders": "Pengingat",
        "ui_change_lang": "Ganti bahasa",
        "ui_switch_book": "Ganti buku",
        "ui_thinking": "sebentar, gw catat...",
        "ui_creating": "bikin buku baru... (30 detik pertama kali)",
        "ui_opening": "buka buku...",
        "ui_creating_note": "Buku baru ditulis ke Walrus dulu sebelum bisa dipakai. Sekitar 30 sampai 40 detik. Jangan tutup halamannya.",
        "ui_lang_set": "Bahasa pack ini: %s",
        "ui_enter_title": "Masuk pakai kunci",
        "ui_enter_note": "Tidak ada akun, tidak ada wallet. Satu kunci satu buku. Simpan kuncinya, itu satu-satunya jalan masuk.",
        "ui_create": "Bikin baru",
        "ui_free_lang": "Bahasa bebas buat nulis. Angka yang tidak jelas ditanya balik.",
        "ui_owed": "utang %s",
        "ui_credit": "kelebihan bayar %s",
        "ui_settled": "lunas",
        "ui_last": "terakhir: %s",
        "ui_none_yet": "belum ada catatan",
        "ui_key_title": "Kunci pack",
        "ui_key_note": "Tempel kunci yang sama di channel lain untuk buku yang sama.",
        "ui_telegram_title": "Pakai buku lewat Telegram",
        "ui_telegram_note": "Buku ini bisa dipakai dari chat Telegram juga. Hubungkan bot dengan kunci buku ini.",
        "ui_telegram_open": "Buka @memorandachatbot di Telegram",
        "ui_telegram_step1": "Tekan Start, lalu kirim /key.",
        "ui_telegram_step2": "Tempel kunci buku yang tampil di atas.",
        "ui_telegram_step3": "Kalau chat sempat timeout, tunggu sebentar lalu kirim ulang kuncinya.",
        "ui_welcome": "Buku kebuka. Tulis kerjaan seperti kamu nulis di chat.",
        "ui_copied": "Kunci disalin.",
        "ui_queued": "%s baris masih di antrean kirim ke Walrus. Catatannya aman, nanti terkirim sendiri.",
        "ui_queued_wait": "%s baris masih di antrean kirim (relayer minta tunggu %s detik). Catatannya aman.",
        "ui_newkey": "Ini kuncimu. Salin dan simpan:",
        "ui_failed": "gagal",
        "ui_no_pack": "belum ada pack",
        "ui_log_title": "Catatan kerjaan",
        "ui_people_title": "Pelanggan",
        "ui_rem_none": "belum ada pengingat",
        "ld_badge": "buat usaha jasa berulang",
        "ld_h1": "Catatan lapangan yang gak lupa.",
        "ld_sub": "Tulis kerjaan hari ini kayak lagi chat. Yang inget sisa utang sama jadwal servis berikutnya, bukan kamu.",
        "ld_cta": "Mulai catat",
        "ld_cta2": "Lihat cara kerjanya",
        "ld_login": "Buka buku",
        "ld_pain_title": "Yang sering kejadian",
        "ld_pain1": "Utang ditulis di nota kertas. Notanya hilang, tagihannya ikut hilang.",
        "ld_pain2": "Pelanggan servis rutin lupa ditawarin lagi, padahal itu langganan.",
        "ld_pain3": "Catatan di HP cuma daftar. Gak ada yang bunyi kalau waktunya ngingetin.",
        "ld_how_title": "Cara kerjanya",
        "ld_how1_t": "Tulis apa aja",
        "ld_how1_b": "Bahasa bebas, angkanya campur, satu pesan bisa banyak kerjaan. Salah tulis tinggal bilang.",
        "ld_how2_t": "Jadi catatan rapi",
        "ld_how2_b": "Kerjaan, bayar, sisa utang, dan jadwal dipisah sendiri. Duitnya dihitung kode, bukan ditebak model.",
        "ld_how3_t": "Pengingatnya dateng",
        "ld_how3_b": "Pengingat masuk ke Telegram. Janji bayar otomatis dicatat; pengingat buat nawarin lagi cuma dibuat kalau lu minta.",
        "ld_demo_title": "Contoh",
        "ld_demo_you": "kamu",
        "ld_demo_it": "buku",
        "ld_demo_note": "Contoh alur: janji pembayaran dicatat; pengingat nawarin lagi hanya muncul karena diminta.",
        "ld_demo_in": "pak jojo servis ac 1/2 PK ganti freon sama cuci AC total 500rb baru di bayar 250rb sisanya dibayar minggu depan. tawarin lagi 3 bulan lagi",
        "ld_demo_out": "Tercatat: Pak Jojo, ac 1/2 PK 500rb.\nBayar 250rb, sisa utang 250rb.\nJanji bayar 01 Okt, gw ingetin.",
        "ld_demo_r1k": "pak jojo", "ld_demo_r1v": "utang 250rb",
        "ld_demo_r2k": "ac 1/2 PK", "ld_demo_r2v": "servis, 24 Sep",
        "ld_demo_r3k": "tagih sisa utang", "ld_demo_r3v": "01 Okt",
        "ld_demo_r4k": "tawarin lagi (diminta)", "ld_demo_r4v": "23 Des",
        "ld_demo_r5k": "sudah dibayar", "ld_demo_r5v": "250rb",
        "ld_why_title": "Kenapa di Walrus",
        "ld_why1": "Catatan disimpan di Walrus, jadi tidak bisa diubah diam-diam. Yang sudah dicatat, tetap tercatat.",
        "ld_why2": "Pengingat dihitung ulang dari saldo tiap kali dibuka. Sudah lunas berarti tidak ada tagihan nyangkut.",
        "ld_who_title": "Buat siapa",
        "ld_who": "Servis AC, bengkel, jahit, kos, les, dan usaha jasa yang pelanggannya balik lagi.",
        "ld_key_note": "Tanpa akun, tanpa wallet, tanpa daftar. Satu kunci satu buku.",
        "ld_footer": "Prototipe. Dibuat untuk DeepSurge Session 8.",
    },
    "en": {
        "ask_person": "Who is the customer?",
        "ask_person_again": "Who is the customer? Write it again with the name in it.",
        "ask_person_clash": "Do you mean %s, or a new person?",
        "ask_amount_bare": "That number is %s. Did you mean %s thousand or %s?",
        "ask_two_amounts": "There are two numbers in that message (%s). One job per entry, so please send them one at a time.",
        "ask_paid_amount": "How much did they pay?",
        "ask_amount": "How much was it?",
        "ask_what": "What should I write down?",
        "confirm_default": "Let me confirm that first.",
        "recap_head": "Noted: %s",
        "recap_job": "%s %s",
        "recap_job_no_amount": "%s",
        "recap_pay": "Paid %s",
        "recap_left": "%s still owed",
        "recap_promise": "Promised to pay %s, I will remind you",
        "recap_followup": "I will remind you to offer again in %s days (%s)",
        "recap_assumed": "(I read %s as thousands, same as the other number in that message)",
        "recap_rounded": "(that number, %s, has cents, so I rounded it to the nearest whole)",
        "recap_mixed_currency": "(you wrote %s in a %s book, so I read that number as written)",
        "recap_queued": "(the entry is still queued for sending, relayer rate limit%s)",
        "recap_queued_wait": ", wait %d seconds",
        "unknown_key": "unknown key",
        "not_understood": "not understood",
        "line_pay": "paid %s",
        "line_collect": "collect %s",
        "line_collect_left": "collect what is still owed",
        "line_offer_again": "offer the %s job again",
        "line_remind": "remind me to %s",
        "line_remind_generic": "follow up with %s",
        "line_alias": "also written: %s",
        # How far away a reminder is, written as a distance. "26 Dec" on its own
        # is what makes somebody ask why a line is there; "in 90 days" is the
        # part that explains it.
        "rem_today": "today",
        "rem_tomorrow": "tomorrow",
        "rem_in_days": "in %d days",
        "rem_late": "%d days late",
        "rem_from": "from the %s job",
        "line_pack": "pack %s",
        "ui_pick_lang": "Choose a language",
        "ui_pick_lang_note": "This language is used for the whole pack. You can change it later in settings.",
        "ui_pick_cur": "Rupiah or dollars?",
        "ui_pick_cur_note": "Answered once, never asked again. A bare \"150\" means different things: 150 thousand in rupiah, 150 dollars in dollars. If your message writes $ or Rp itself, that one wins.",
        "ui_cur_idr": "Rupiah (Rp)",
        "ui_cur_usd": "USD ($)",
        "ui_cur_label": "Money",
        "ui_change_cur": "Change money",
        "ui_timezone": "Timezone",
        "ui_change_timezone": "Change timezone",
        "ui_timezone_note": "New reminders use the book's current timezone.",
        "ui_tz_jakarta": "WIB (Jakarta)",
        "ui_tz_makassar": "WITA (Makassar)",
        "ui_tz_jayapura": "WIT (Jayapura)",
        "ui_tz_singapore": "Singapore",
        "ui_tz_bangkok": "Bangkok",
        "ui_tz_utc": "UTC",
        "ui_tz_london": "London",
        "ui_tz_new_york": "New York",
        "ui_tz_los_angeles": "Los Angeles",
        "ui_tz_saved": "Timezone changed to %s.",
        "ui_tz_confirm_title": "Timezone for reminders",
        "ui_tz_confirm_note": "Your first dated reminder will use this timezone. You can change it later in settings.",
        "ui_tz_error": "The timezone could not be changed.",
        "ui_cur_now": "Money is now %s. A bare number is read that way.",
        # The same four kinds of business, written in the language of the page.
        "ui_biz_ac_service": "AC repair",
        "ui_biz_workshop": "Workshop",
        "ui_biz_tailor": "Tailor",
        "ui_biz_generic": "Other business",
        "ui_key_ph": "paste your key here",
        "ui_open": "Open",
        "ui_new_ph": "e.g. Prima Jaya",
        "ui_pick_biz": "Business type",
        "ui_pick_name": "Shop name (optional)",
        "ui_or_new": "or start a new book",
        "ui_new": "Create new",
        "ui_say_ph": "e.g. 21 sep serviced Budi living room AC, refilled freon 150, unpaid, next 3 months",
        "ui_send": "Send",
        "ui_copy": "Copy key",
        "ui_refresh": "Reload",
        "ui_people": "People",
        "ui_reminders": "Reminders",
        "ui_change_lang": "Change language",
        "ui_switch_book": "Switch book",
        "ui_thinking": "one moment, writing it down...",
        "ui_creating": "creating the book... (first time takes 30s)",
        "ui_opening": "opening the book...",
        "ui_creating_note": "A new book is written to Walrus before it can be used. That is 30 to 40 seconds. Do not close the page.",
        "ui_lang_set": "Pack language: %s",
        "ui_enter_title": "Open with a key",
        "ui_enter_note": "No account, no wallet. One key, one book. Keep the key, it is the only way back in.",
        "ui_create": "Create new",
        "ui_free_lang": "Write in any language. A number that is not clear gets asked about.",
        "ui_owed": "%s owed",
        "ui_credit": "%s overpaid",
        "ui_settled": "settled",
        "ui_last": "last: %s",
        "ui_none_yet": "nothing recorded yet",
        "ui_key_title": "Pack key",
        "ui_key_note": "Paste the same key in another channel for the same book.",
        "ui_telegram_title": "Use this book in Telegram",
        "ui_telegram_note": "You can use this book from Telegram too. Connect the bot with this book key.",
        "ui_telegram_open": "Open @memorandachatbot in Telegram",
        "ui_telegram_step1": "Press Start, then send /key.",
        "ui_telegram_step2": "Paste the book key shown above.",
        "ui_telegram_step3": "If the chat timed out, wait a bit and send the key again.",
        "ui_welcome": "The book is open. Write the job the way you would type it in a chat.",
        "ui_copied": "Key copied.",
        "ui_queued": "%s lines are still queued to Walrus. The entry is safe, it sends itself.",
        "ui_queued_wait": "%s lines are still queued (the relayer asked to wait %s seconds). The entry is safe.",
        "ui_newkey": "This is your key. Copy it and keep it:",
        "ui_failed": "failed",
        "ui_no_pack": "no pack yet",
        "ui_log_title": "Job notes",
        "ui_people_title": "Customers",
        "ui_rem_none": "no reminders yet",
        "ld_badge": "for repeat service work",
        "ld_h1": "Field notes that don't forget.",
        "ld_sub": "Type today's work like you're chatting. The book is what remembers who still owes you, and when the next service is due.",
        "ld_cta": "Start a book",
        "ld_cta2": "See how it works",
        "ld_login": "Open a book",
        "ld_pain_title": "What keeps happening",
        "ld_pain1": "Debts go on paper slips. The slip goes missing, so does the money you were owed.",
        "ld_pain2": "Regular customers never get offered the next service, even though they always say yes.",
        "ld_pain3": "Phone notes are just lists. Nothing ever speaks up when it is time to act.",
        "ld_how_title": "How it works",
        "ld_how1_t": "Type it however",
        "ld_how1_b": "Any language, messy numbers, several jobs in one message. Get it wrong and just say so.",
        "ld_how2_t": "It files itself",
        "ld_how2_b": "Jobs, payments, what is still owed and what is scheduled are split apart. The money is arithmetic, not a guess.",
        "ld_how3_t": "The reminders arrive",
        "ld_how3_b": "A payment promise can create a reminder after it is recorded. An offer-again reminder is only added when you request one.",
        "ld_demo_title": "Illustrative flow (USD)",
        "ld_demo_you": "you",
        "ld_demo_it": "the book",
        "ld_demo_note": "Illustrative exchange to explain the flow; amounts and dates are examples, not a live account.",
        # The Indonesian block above is the real-run illustration. The English
        # version shows the same steps in USD for visitors; don't present the
        # displayed dollar parsing as verified production behavior.
        "ld_demo_in": "jojo AC service, refilled the freon and washed the unit, $120, paid $60 so far; promised the rest next week; offer again in 3 months",
        "ld_demo_out": "Example: Jojo, AC service $120.\nPaid $60, $60 still owed.\nPromise to pay next week → reminder.\nOffer-again reminder in 3 months → only because requested.",
        "ld_demo_r1k": "jojo", "ld_demo_r1v": "$60 owed",
        "ld_demo_r2k": "AC unit", "ld_demo_r2v": "serviced, 24 Sep",
        "ld_demo_r3k": "collect owed", "ld_demo_r3v": "01 Oct",
        "ld_demo_r4k": "offer again (asked)", "ld_demo_r4v": "23 Dec",
        "ld_demo_r5k": "already paid", "ld_demo_r5v": "$60",
        "ld_why_title": "Why Walrus",
        "ld_why1": "Notes live on Walrus, so they cannot be quietly edited. What was written stays written.",
        "ld_why2": "Reminders are worked out again from the balance every time it is read. Somebody who paid in full is not chased.",
        "ld_who_title": "Who it is for",
        "ld_who": "AC repair, workshops, tailors, boarding houses, tutors, and any service where customers come back.",
        "ld_key_note": "No account, no wallet, no signup. One key, one book.",
        "ld_footer": "Prototype. Built for DeepSurge Session 8.",
    },
}


def t(lang, key, *args):
    """One code-written string. Falls back to Indonesian, then to the key."""
    table = STRINGS.get(lang) or {}
    text = table.get(key) or STRINGS[DEFAULT_LANG].get(key) or key
    return text % args if args else text


def ui_bundle(lang):
    """Everything the page needs to render itself in one language.

    A language we have no table for gets English buttons rather than Indonesian
    ones. English is the safer fallback: a Spanish speaker reading "Send" is
    fine, a Spanish speaker reading "Kirim" is not.
    """
    table = STRINGS.get(lang) or STRINGS["en"]
    keys = {k: v for k, v in STRINGS["en"].items()
            if k.startswith("ui_") or k.startswith("ld_")}
    out = {}
    for key in keys:
        out[key] = table.get(key) or STRINGS["en"].get(key) \
            or STRINGS[DEFAULT_LANG].get(key) or keys[key]
    out["lang"] = lang
    out["lang_name"] = prompt_name(lang)
    out["brand"] = BRAND
    return out


# ---------------------------------------------------------------------------
# what the bot itself says
# ---------------------------------------------------------------------------
# The notebook's own words live in STRINGS above and travel with the pack, in
# Walrus. These are the things the channel says, so they are chosen by the pack's
# language too but not stored per pack. Kept here rather than in the bot module
# so there is exactly one table of languages in the project.
BOT_STRINGS = {
    "id": {
        "hi": "Halo. Ini buku catatan lapangan lu.\n\n"
              "Tulis aja kayak ngomong, contoh:\n"
              "\"pak jojo servis ac 500rb baru bayar 250rb sisanya minggu depan\"\n\n"
              "Yang inget siapa masih utang dan kapan harus nengok lagi: buku ini, "
              "bukan lu.",
        # The command names themselves are not here on purpose. They live in
        # commands.py, and /help is assembled from that table, so renaming a
        # command can never leave the help text lying.
        "help_head": "Yang bisa lu ketik:",
        "help_tail": "Selain itu, ketik apa aja. Pesan buat catatan masuk ke buku. Tawarin pelanggan lagi cuma diingatkan kalau lu minta, misalnya: \"servis AC Jojo, tawarin lagi 3 bulan lagi\".",
        "cmd_start": "mulai dari sini",
        "cmd_help": "daftar perintah ini",
        "cmd_new": "bikin buku baru",
        "cmd_key": "sambungin ke buku yang udah punya",
        "cmd_book": "liat isi buku sekarang",
        "cmd_remind": "lihat pengingat terjadwal; tawarin lagi cuma kalau diminta",
        "cmd_timezone": "lihat zona waktu buku yang sedang dipakai",
        "tz_current": "Zona waktu buku: %s — %s. Ubah lewat setelan zona waktu.",
        "tz_invalid": "Zona waktu gak dikenal. Contoh: %s",
        "tz_saved": "Zona waktu buku diubah ke %s — %s. Pengingat lama mempertahankan zona saat dibuat.",
        "cmd_release": "lepas buku dari chat ini",
        "new_ok": "Buku baru jadi.\n\nKunci buku lu:\n\n%s\n\n"
                  "Simpen kunci ini. Satu kunci satu buku, tanpa akun dan tanpa "
                  "daftar, jadi ini satu-satunya jalan balik ke buku ini.",
        "bound": "Nyambung. Mulai sekarang semua yang lu ketik masuk ke buku ini.",
        # The %s slots are filled with whatever commands.py says the commands
        # are called. Nothing in this file names a command, so changing the
        # language of the commands cannot leave a message pointing at a command
        # that no longer exists.
        "bad_key": "Kunci itu gak ketemu. Cek lagi hurufnya, atau ketik %s.",
        "need_key": "Kuncinya dikirim barengan perintahnya, satu pesan.\n\n"
                    "Contoh:\n%s Kd9xAb12\n\n"
                    "Tempel kuncinya sendiri juga kebaca.",
        "unbound": "Chat ini belum nyambung ke buku apa pun.\n\n"
                   "Ketik %s buat bikin buku baru, atau %s <kunci> kalau udah punya.",
        "released": "Buku dilepas dari chat ini. Isinya tetap aman di Walrus, "
                    "tinggal %s lagi kalau mau balik.",
        "book_head": "BUKU",
        "debt_head": "PENGINGAT",
        "shop_head": "Toko: %s",
        "empty": "Buku ini masih kosong. Tulis aja satu kalimat.",
        "no_rem": "Belum ada pengingat yang nunggu.",
        "followup_manual": "Pengingat untuk nawarin lagi cuma dibuat kalau lu minta. Contoh: \"servis AC Jojo, tawarin lagi 3 bulan lagi\".",
        "owed": "utang",
        "credit": "lebih bayar",
        "paid": "udah bayar",
        "down": "Buku-nya lagi gak bisa dihubungi. Coba lagi sebentar.",
        "error": "Ada yang rusak di sisi gw: %s",
        "work": "Contoh: \"bu sari jahit 2 potong 180rb belum bayar, ambil minggu depan\"",
    },
    "en": {
        "hi": "Hello. This is your field notebook.\n\n"
              "Write it the way you talk, for example:\n"
              "\"jojo serviced an AC for 500k, paid 250k, rest next week\"\n\n"
              "The thing that remembers who still owes you and when to look again "
              "is this book, not you.",
        "help_head": "What you can type:",
        "help_tail": "Messages that log work go in the book. I only remind you to offer a customer again when you ask, for example: \"serviced Jojo's AC; offer again in 3 months\".",
        "cmd_start": "start here",
        "cmd_help": "this list",
        "cmd_new": "make a new book",
        "cmd_key": "connect to a book you already have",
        "cmd_book": "see what is in the book now",
        "cmd_remind": "see scheduled reminders; offer-again notes are opt-in",
        "cmd_timezone": "see the book timezone currently in use",
        "tz_current": "Book timezone: %s — %s. Change it in the timezone settings.",
        "tz_invalid": "Unknown timezone. Examples: %s",
        "tz_saved": "Book timezone changed to %s — %s. Existing reminders keep the timezone they were created with.",
        "cmd_release": "unbind the book from this chat",
        "new_ok": "New book created.\n\nYour book key:\n\n%s\n\n"
                  "Keep this key. One key, one book, no account and no signup, so "
                  "it is the only way back in.",
        "bound": "Connected. Everything you type now goes into this book.",
        "bad_key": "That key was not found. Check the letters, or type %s.",
        "need_key": "Send the key together with the command, in one message.\n\n"
                    "Example:\n%s Kd9xAb12\n\n"
                    "Pasting the key on its own works too.",
        "unbound": "This chat is not connected to a book yet.\n\n"
                   "Type %s to make one, or %s <key> if you already have one.",
        "released": "Book released from this chat. It is still safe on Walrus, "
                    "just use %s again to come back.",
        "book_head": "BOOK",
        "debt_head": "REMINDERS",
        "shop_head": "Shop: %s",
        "empty": "This book is empty. Type one sentence.",
        "no_rem": "No reminders are waiting.",
        "followup_manual": "Offer-again reminders are only created when you ask. Example: \"serviced Jojo's AC; offer again in 3 months\".",
        "owed": "owes",
        "credit": "in credit",
        "paid": "paid so far",
        "down": "The notebook cannot be reached right now. Try again shortly.",
        "error": "Something broke on my side: %s",
        "work": "Example: \"sari ran up a 180k tailoring job, unpaid, pick up next week\"",
    },
}


def bot_string(lang, key, *args):
    """One line the channel says. English unless the pack is Indonesian."""
    table = BOT_STRINGS.get(lang) or BOT_STRINGS["en"]
    text = table.get(key) or BOT_STRINGS["en"].get(key) or key
    return text % args if args else text


# ---------------------------------------------------------------------------
# money and dates, in the shape each language writes them
# ---------------------------------------------------------------------------

MONTHS = {
    "id": ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt",
           "Nov", "Des"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
           "Nov", "Dec"),
}


def money(rupiah, lang=DEFAULT_LANG, currency=None):
    """150000 -> 150rb (id), 150k (en), 150,000 (anything else).

    English speakers do not read "rb" and Indonesian speakers do not read "k" in
    the same breath, and this string ends up inside a sentence a customer might
    even see, so it is not a cosmetic detail.

    The currency is a second setting, and it only adds its mark when it is known
    to be dollars. A rupiah figure is written the way rupiah is written, with no
    mark, because "Rp" in front of "150rb" is not how anybody says it out loud.
    """
    return _money_body(rupiah, lang) if currency != "USD" \
        else "$" + _money_body(rupiah, lang)


def _money_body(rupiah, lang=DEFAULT_LANG):
    """The number without any mark in front of it.

    The millions test comes before the thousands test on purpose: 1500000 is
    1,5jt, and the thousands branch used to answer "1500rb" for it because
    1500000 % 1000000 is 500000 rather than 0.
    """
    value = int(rupiah or 0)
    if not value:
        return "0"
    if lang == "id":
        if value >= 1000000:
            if value % 1000000 == 0:
                return "%sjt" % (value // 1000000)
            return ("%.1fjt" % (value / 1000000.0)).replace(".", ",")
        if value % 1000 == 0:
            return "%srb" % (value // 1000)
        return str(value)
    if lang == "en":
        if value >= 1000000:
            return "%sm" % (value // 1000000) if value % 1000000 == 0 \
                else "%.1fm" % (value / 1000000.0)
        if value % 1000 == 0:
            return "%sk" % (value // 1000)
        return "{:,}".format(value)
    return "{:,}".format(value)


def short_date(when, lang=DEFAULT_LANG):
    months = MONTHS.get(lang, MONTHS["id"])
    return "%02d %s" % (when.day, months[when.month - 1])


# ---------------------------------------------------------------------------
# the check: does the sentence actually come back in the right language
# ---------------------------------------------------------------------------

# Function words only. Names, places and job words get copied verbatim from the
# worker's message and can legitimately belong to another language, so anything
# that could appear inside "Pak Asep" or "servis AC" is kept out of these lists.
STOPWORDS = {
    "id": frozenset("""
        yang dan atau dengan untuk dari kalau kalo gak nggak tidak belum sudah udah
        ini itu apa berapa jadi masih akan lagi dulu aja saja tolong maaf terima kasih
        sisa utang bayar tagih kerjaan pelanggan saya kami anda dia mereka bisa harus
        karena juga sudah disimpan nanti kemarin besok hari bulan minggu tahun
    """.split()),
    "en": frozenset("""
        the and or with for from if not yet already has have had was were are is
        this that what how much still will would can should because also please sorry
        thanks left owing owed paid pay money job customer you your they their
        recorded saved tomorrow yesterday today week month year
    """.split()),
    "es": frozenset("""
        el la los las y o con para de si no ya ha han fue eran es esta esto
        que cuanto todavia sera puede deberia porque tambien gracias perdone
        queda debe pago pagado dinero trabajo cliente usted su
    """.split()),
    "pt": frozenset("""
        o os as e ou com para de se nao ja foi foram era sao esta isso
        que quanto ainda sera pode deveria porque tambem obrigado desculpe
        falta deve pagamento pago dinheiro trabalho cliente voce seu
    """.split()),
    "ms": frozenset("""
        yang dan atau dengan untuk dari kalau tak tidak belum sudah ini itu apa
        berapa jadi masih akan lagi dulu sahaja tolong maaf terima kasih
        baki hutang bayar kerjaan pelanggan saya kami anda dia mereka boleh
        kerana juga disimpan nanti semalam esok hari bulan minggu tahun
    """.split()),
    "fr": frozenset("""
        le la les et ou avec pour de si ne pas deja a ete etaient est ce
        que combien encore sera peut devrait parce aussi merci desole
        reste doit paiement paye argent travail client vous votre
    """.split()),
    "de": frozenset("""
        der die das und oder mit fur von wenn nicht schon hat haben war waren ist
        das dies was wie viel noch wird kann sollte weil auch danke
        bleibt schuldet zahlung bezahlt geld arbeit kunde sie ihr
    """.split()),
}

# Languages we can settle without a word list, because the alphabet gives it away.
SCRIPTS = {
    "hi": ("\u0900", "\u097f"),   # devanagari
    "bn": ("\u0980", "\u09ff"),
    "ar": ("\u0600", "\u06ff"),
    "fa": ("\u0600", "\u06ff"),
    "ur": ("\u0600", "\u06ff"),
    "he": ("\u0590", "\u05ff"),
    "ru": ("\u0400", "\u04ff"),
    "uk": ("\u0400", "\u04ff"),
    "th": ("\u0e00", "\u0e7f"),
    "zh": ("\u4e00", "\u9fff"),
    "ja": ("\u3040", "\u30ff"),
    "ko": ("\uac00", "\ud7af"),
}

WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
MIN_HITS = 2


def _letters(text):
    return [w.lower() for w in WORD_RE.findall(unicodedata.normalize("NFKC", text or ""))]


def script_of(text, lang):
    """How much of this text is written in the alphabet that language uses."""
    span = SCRIPTS.get(lang)
    if not span:
        return 0
    low, high = span
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return 0
    hits = sum(1 for c in letters if low <= c <= high)
    return hits / float(len(letters))


def score(text, lang):
    words = _letters(text)
    if not words:
        return 0
    bag = STOPWORDS.get(lang)
    if not bag:
        return 0
    return sum(1 for w in words if w in bag)


def detect(text):
    """Best guess at the language, or None when nothing is convincing.

    Silence is the right answer for a two-word reply: "Oke." is in every
    language, and a wrong retry costs a call for nothing.
    """
    for lang, span in sorted(SCRIPTS.items()):
        if script_of(text, lang) > 0.5:
            return lang
    scored = sorted(((score(text, lang), lang) for lang in STOPWORDS), reverse=True)
    if scored and scored[0][0] >= MIN_HITS:
        return scored[0][1]
    return None


def conforms(text, lang, name=""):
    """(is it in the language we asked for, what it looks like, was it settled).

    Only a confident mismatch is refused. An unchecked language (one the person
    typed that we have no data for) comes back settled=False, which the caller
    reports instead of pretending it verified anything.
    """
    text = str(text or "")
    if lang in SCRIPTS:
        return (script_of(text, lang) > 0.5, detect(text), True)
    if lang in STOPWORDS:
        want = score(text, lang)
        found = detect(text)
        if found is None or found == lang:
            return (True, found, True)
        other = score(text, found)
        if other >= MIN_HITS and other > want:
            return (False, found, True)
        return (True, found, True)
    # A language we have no words for. Script still says something when the
    # alphabet is distinctive, but a mismatch is a warning, not a verdict.
    found = detect(text)
    if found and found in SCRIPTS and script_of(text, found) > 0.5:
        return (True, found, False)
    return (True, found, False)
