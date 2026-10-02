"""Offline regression checks for book timezone persistence and reminders."""
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import packlib
import timezones
import parse
import lang

passed = []
failed = []

def check(name, actual, expected):
    (passed if actual == expected else failed).append(name)
    print(("ok   " if actual == expected else "FAIL ") + name)
    if actual != expected:
        print("     got:  %r\n     want: %r" % (actual, expected))

# Old packs with no timezone retain the product's WIB fallback.
old = packlib.fold(["Buku lama #k:pack #pk:old #lang:id #cur:IDR #at:2026-09-27T10:00:00"])
check("legacy pack defaults to Jakarta", old["pack"]["tz"], "Asia/Jakarta")
tagged = packlib.fold(["Buku #k:pack #pk:x #tz:Asia/Makassar #at:2026-09-27T10:00:00"])
body = packlib.fold(["Buku timezone=Asia/Jayapura #k:pack #pk:y #at:2026-09-27T10:00:00"])
check("timezone tag folds", tagged["pack"]["tz"], "Asia/Makassar")
check("legacy timezone body folds", body["pack"]["tz"], "Asia/Jayapura")

# Old reminders (no tz tag) freeze the book timezone in force when folded;
# explicit reminder tz wins if a book's setting changes later.
legacy_rem = packlib.fold([
    "Buku #k:pack #pk:x #tz:Asia/Jakarta #at:2026-09-27T10:00:00",
    "Tagih #k:rem #p:jo #fire:2026-10-01T09:00:00 #kind:collect #at:2026-09-27T10:00:00",
])
check("legacy reminder timezone inherited from pack", legacy_rem["reminders"][0]["timezone"], "Asia/Jakarta")

# Reminder creation carries the current pack timezone through to its Walrus line.
proposal = {"intent":"log", "person":"Budi", "subject":"AC", "subject_type":"ac_unit",
            "job_type":"service", "date_text":None, "date_in_days":0,
            "followup_after_days":7,
            "items":[{"kind":"job","amount_text":"150rb"}], "_raw":"service Budi AC 150rb"}
planned = parse.plan(proposal, {"people":{}, "timezone":"Asia/Makassar"},
                     datetime(2026,9,28,10), lang_code="id")
check("plan entries preserve book timezone", {e["timezone"] for e in planned["entries"] if "timezone" in e}, {"Asia/Makassar"})
lines = parse.lines_for(planned, lang_code="id")
reminder_lines = [line for line in lines if packlib.kind_of(line) == "rem"]
check("new reminder line persists creation timezone",
      [packlib.tags_of(line).get("tz") for line in reminder_lines], ["Asia/Makassar"])

# Legacy naive reminder keys match pre-timezone sent markers exactly. New aware
# reminders include their offset so equal wall times in separate zones do not collide.
check("legacy naive ID matches old marker",
      timezones.reminder_identity("2026-10-01T09:00:00", "Asia/Jakarta"),
      "2026-10-01T09:00:00")
check("aware IDs use stable UTC marker",
      timezones.reminder_identity("2026-10-01T09:00:00+08:00", "Asia/Makassar"),
      "2026-10-01T01:00:00")
check("naive IDs remain legacy-walltime based",
      timezones.reminder_identity("2026-10-01T09:00:00", "Asia/Jakarta"),
      timezones.reminder_identity("2026-10-01T09:00:00", "Asia/Makassar"))
check("equal aware instants normalize to same ID",
      timezones.reminder_identity("2026-10-01T09:00:00+07:00", "Asia/Jakarta"),
      timezones.reminder_identity("2026-10-01T10:00:00+08:00", "Asia/Makassar"))

# A reminder carries its creation zone; changing only the current pack zone must
# not re-interpret its existing local fire time.
frozen = packlib.fold([
    "Buku #k:pack #pk:x #tz:Asia/Makassar #at:2026-09-27T10:00:00",
    "Tagih #k:rem #p:jo #fire:2026-10-01T09:00:00 #tz:Asia/Jakarta #at:2026-09-27T10:00:00",
])
frozen["pack"]["tz"] = "Asia/Makassar"
check("stored reminder zone survives later pack-zone update",
      frozen["reminders"][0]["timezone"], "Asia/Jakarta")

# Absolute due comparison checks that 09:00 WIB is 02:00 UTC.
now_before = datetime(2026, 10, 1, 1, 59, tzinfo=timezone.utc)
now_due = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
check("Jakarta reminder is not early", timezones.due_in_timezone("2026-10-01T09:00:00", now_before, "Asia/Jakarta"), False)
check("Jakarta reminder due at local 09:00", timezones.due_in_timezone("2026-10-01T09:00:00", now_due, "Asia/Jakarta"), True)
check("WITA aware reminder due at local 09:00",
      timezones.due_in_timezone("2026-10-01T09:00:00+08:00",
                                datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc),
                                "Asia/Jakarta"), True)

# UI timezone options and actions must be sourced from translated bundles.
import re
for filename in ("index.html", "home.html"):
    html = open(os.path.join(HERE,"web",filename), encoding="utf-8").read()
    opts = re.findall(r'<option\b[^>]*>([^<]*)</option>',html)
    check(filename + " has no hardcoded option labels", [x.strip() for x in opts if x.strip()], [])
    keys = set(re.findall(r'data-i18n(?:-ph)?="([a-z0-9_]+)"',html))
    bundle = lang.ui_bundle("en")
    check(filename + " all i18n keys exist", sorted(keys-set(bundle)), [])

print("%d passed, %d failed" % (len(passed), len(failed)))
sys.exit(bool(failed))
