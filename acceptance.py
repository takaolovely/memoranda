#!/usr/bin/env python3
"""The acceptance scenario from the brief, run against the live prototype.

Creates a fresh pack, drives it with the exact sentence from the brief, and
checks every line of the acceptance list. Talks to the running server over HTTP,
so what it measures is what a browser would get.

    python3 acceptance.py                 # against http://127.0.0.1:8770
    python3 acceptance.py --url http://... --keep
"""
import argparse
import json
import sys
import time
import urllib.request

RESULTS = []


def call(url, path, payload=None, timeout=240):
    full = url.rstrip("/") + path
    if payload is None:                      # a read, not a write
        with urllib.request.urlopen(full, timeout=timeout) as resp:
            return json.load(resp)
    req = urllib.request.Request(full, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def step(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print("%s %s%s" % ("ok  " if ok else "FAIL", name,
                       ("  -> %s" % detail) if detail else ""))
    return ok


def owes(state, who="pak budi"):
    for person in (state or {}).get("people", []):
        if person["name"].lower() == who:
            return person["owes"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8770")
    ap.add_argument("--keep", action="store_true", help="print the passkey and stop")
    args = ap.parse_args()
    url = args.url

    health = call(url, "/api/health")
    step("server hidup", health.get("ok"))

    made = call(url, "/api/pack", {"action": "create", "biz": "ac_service",
                                   "name": "Tukang AC Demo"})
    step("pack baru dibuat dan barisnya mendarat di Walrus", made.get("landed"),
         "pack %s" % made.get("pack_id"))
    key = made["passkey"]
    print("     passkey: %s" % key)
    if args.keep:
        return 0

    first = call(url, "/api/turn", {
        "passkey": key,
        "text": "21 sep servis AC pak budi ruang tamu isi freon 150 belum lunas next 3 bulan"})
    step("angka tanpa satuan ditanya balik, bukan ditebak",
         first.get("kind") == "confirm" and "150" in (first.get("say") or ""),
         first.get("say"))

    second = call(url, "/api/turn", {"passkey": key, "text": "150rb"})
    step("setelah diperjelas, tercatat dan mendarat",
         second.get("kind") == "committed" and second.get("landed"),
         second.get("say"))
    step("saldo Budi jadi 150rb", owes(second.get("state")) == 150000,
         "owes=%s" % owes(second.get("state")))

    subject = None
    for person in (second.get("state") or {}).get("people", []):
        for sub in person.get("subjects", []):
            subject = sub
    step("subject AC ruang tamu tercatat",
         bool(subject) and subject["label"].lower().startswith("ac"),
         json.dumps(subject))

    asked = call(url, "/api/turn", {"passkey": key, "text": "pak budi ngutang berapa"})
    step("ditanya utang, dijawab dari memori", "150" in (asked.get("say") or ""),
         asked.get("say"))

    when = call(url, "/api/turn", {"passkey": key, "text": "ac ruang tamu terakhir kapan"})
    step("ditanya kapan terakhir, dijawab 21 September",
         "21" in (when.get("say") or "") and "sep" in (when.get("say") or "").lower(),
         when.get("say"))

    again = call(url, "/api/turn", {
        "passkey": key,
        "text": "21 sep servis AC pak budi ruang tamu isi freon 150rb belum lunas next 3 bulan"})
    step("kalimat yang sama tidak menggandakan utang",
         owes(again.get("state")) == 150000, "owes=%s" % owes(again.get("state")))

    # one message holding two facts, which is how it was reported broken
    mixed = call(url, "/api/turn", {
        "passkey": key,
        "text": "pak asep ngutang total biaya service 250rb dia baru bayar 100 "
                "nanti dibayar minggu depan"})
    step("satu pesan berisi kerjaan dan pembayaran, dua-duanya tercatat",
         "150" in (mixed.get("say") or "") and owes(mixed.get("state"), "pak asep") == 150000,
         "%s | owes=%s" % (mixed.get("say"), owes(mixed.get("state"), "pak asep")))

    paid = call(url, "/api/turn", {"passkey": key, "text": "pak budi sudah bayar 150rb"})
    step("bayar tercatat dan saldo jadi nol",
         paid.get("kind") == "committed" and owes(paid.get("state")) == 0,
         "%s | owes=%s" % (paid.get("say"), owes(paid.get("state"))))

    # a fresh read, so the answer has to come back out of Walrus
    time.sleep(2)
    fresh = call(url, "/api/state", {"passkey": key})
    step("bacaan baru dari Walrus tetap nol dan tidak kehilangan baris",
         owes(fresh.get("state")) == 0,
         "owes=%s" % owes(fresh.get("state")))

    reminders = fresh.get("reminders") or []
    step("reminder follow-up 90 hari tercatat di pack", bool(reminders),
         json.dumps(reminders[:1], ensure_ascii=False))

    failed = [name for name, ok in RESULTS if not ok]
    print()
    print("%d/%d lolos" % (len(RESULTS) - len(failed), len(RESULTS)))
    if failed:
        print("gagal: %s" % ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
