"""The outbox count must ignore outboxes whose pack no longer exists.

The flusher only walks packs listed in packs.json, so an outbox left behind by a
removed pack can never drain. Counting it held /api/health permanently above
zero, which hides a real backlog. Seen live: a single line from a deleted pack
kept the queue at 1 for eight days.
"""

import json
import os
import shutil
import tempfile

import server

failures = 0


def check(label, got, want):
    global failures
    if got == want:
        print("ok   %s" % label)
    else:
        failures += 1
        print("FAIL %s: got %r want %r" % (label, got, want))


root = tempfile.mkdtemp(prefix="outbox-test-")
real_data, real_packs = server.DATA, server.PACKS_PATH
try:
    server.DATA = root
    server.PACKS_PATH = os.path.join(root, "packs.json")

    json.dump({"deadbeef": {"namespace": "fieldpack:live1"}},
              open(server.PACKS_PATH, "w", encoding="utf-8"))

    with open(os.path.join(root, "fieldpack_live1.pending.jsonl"), "w",
              encoding="utf-8") as fh:
        fh.write('{"text": "one"}\n{"text": "two"}\n')

    # the orphan: its pack is not in packs.json, so nothing will ever flush it
    with open(os.path.join(root, "fieldpack_gone.pending.jsonl"), "w",
              encoding="utf-8") as fh:
        fh.write('{"text": "left behind"}\n')

    check("counts only live outboxes", server.queued_total(), 2)

    with open(os.path.join(root, "fieldpack_live1.pending.jsonl"), "w",
              encoding="utf-8") as fh:
        fh.write("")
    check("an empty live outbox adds nothing", server.queued_total(), 0)

    os.remove(os.path.join(root, "fieldpack_live1.pending.jsonl"))
    check("orphan alone reports zero", server.queued_total(), 0)

    with open(os.path.join(root, "fieldpack_live1.pending.jsonl"), "w",
              encoding="utf-8") as fh:
        fh.write('{"text": "back"}\n')
    check("live line is visible again", server.queued_total(), 1)
finally:
    server.DATA, server.PACKS_PATH = real_data, real_packs
    shutil.rmtree(root, ignore_errors=True)

print()
if failures:
    print("%d failed" % failures)
    raise SystemExit(1)
print("all outbox tests passed")
