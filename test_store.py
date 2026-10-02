"""The reading path, tested against failure modes instead of a healthy relayer.

Walrus reads are a similarity search with an indexing delay, so "it came back"
and "it came back complete" are different questions. The bug that started this
file: a payment was written, the relayer accepted it, and the next question about
the balance answered with the number from before the payment, because the read
returned the older lines and stopped there.

The fake client can lag, refuse, or land. No network, no model.

Run:  .venv/bin/python test_store.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import packlib  # noqa: E402

FAILS = []


def check(name, got, want):
    if got == want:
        print("ok   %s" % name)
    else:
        print("FAIL %s\n       got  %r\n       want %r" % (name, got, want))
        FAILS.append(name)


class Item:
    def __init__(self, text):
        self.text = text


class Result:
    def __init__(self, texts):
        self.results = [Item(t) for t in texts]


class FakeClient:
    """A relayer that can lag behind what it has already accepted."""

    def __init__(self, lands=True):
        self.mem = []
        self.lands = lands
        self.stale_at = None      # freeze the visible view at this many lines
        self.writes = 0

    def recall(self, query, limit, namespace, max_distance):
        if self.stale_at is None:
            return Result(list(self.mem))
        return Result(list(self.mem[:self.stale_at]))

    def remember_bulk_and_wait(self, items):
        if not self.lands:
            raise RuntimeError("429 rate limit exceeded")
        self.writes += 1
        for item in items:
            self.mem.append(item.text)


JOB = ("21 sep serviced Budi AC 250rb #k:job #p:budi #job:j1 #amount:250000 "
       "#type:servis #at:2026-09-21T09:00:00.000001")
PAY = "bayar 100rb #k:pay #p:budi #ref:j1 #amount:100000 #at:2026-09-22T09:00:00.000001"
PERSON = "Budi #k:person #p:budi #name:Budi #at:2026-09-02T09:00:00.000001"

root = tempfile.mkdtemp(prefix="fieldpack-test-")
try:
    # --- the healthy path ---------------------------------------------------
    client = FakeClient()
    store = packlib.PackStore("fieldpack:t1", client, root=root)
    store.write_many([PERSON, JOB])
    check("kerjaan mendarat dan saldonya benar",
          store.state()["people"]["budi"]["balance"], 250000)
    store.write_many([PAY])
    check("bayar ikut terhitung", store.state()["people"]["budi"]["balance"], 150000)

    # --- the read that lags behind the write --------------------------------
    client = FakeClient()
    store = packlib.PackStore("fieldpack:t2", client, root=root)
    store.write_many([PERSON, JOB])
    client.stale_at = len(client.mem)     # the index stops growing from here
    store.write_many([PAY])
    check("walrus yang basi tidak bikin saldo salah",
          store.state()["people"]["budi"]["balance"], 150000)
    check("salinan lokal juga yang menyelamatkan pertanyaan berikutnya",
          packlib.summary(store.state())["people"][0]["paid_total"], 100000)

    # --- the write the relayer keeps refusing -------------------------------
    client = FakeClient(lands=False)
    store = packlib.PackStore("fieldpack:t3", client, root=root)
    landed, waiting = store.write_many([PERSON, JOB, PAY])[0:2]
    check("ditolak tidak berarti hilang", landed, False)
    check("barisnya menunggu di antrean", store.queued(), 3)
    check("saldo tetap benar walau belum mendarat",
          store.state()["people"]["budi"]["balance"], 150000)
    check("salinan lokal menyimpan semuanya", len(store.journal()), 3)

    # --- the same three lines, in a second run, from the local copy ---------
    store2 = packlib.PackStore("fieldpack:t3", FakeClient(lands=False), root=root)
    check("pack yang sama dibuka ulang tetap punya isinya",
          store2.state()["people"]["budi"]["balance"], 150000)

    # --- the journal is a real backup file, one line per fact ---------------
    with open(store2.journal_path, encoding="utf-8") as fh:
        rows = [line for line in fh if line.strip()]
    check("satu baris satu catatan", len(rows), 3)
    check("bisa dibaca manusia", '"text"' in rows[0], True)

    # --- a write slower than any person would wait for ----------------------
    # The measured write is twenty to forty seconds. Waiting for it inside the
    # request is what made a reply take fifty seconds, so the request gives up
    # early, the outbox is shut so the flusher does not send a second copy while
    # the abandoned attempt is still in the air, and the abandoned attempt clears
    # the outbox itself when it succeeds.
    import time as _time

    class SlowClient(FakeClient):
        def __init__(self, delay):
            FakeClient.__init__(self)
            self.delay = delay

        def remember_bulk_and_wait(self, items):
            _time.sleep(self.delay)
            FakeClient.remember_bulk_and_wait(self, items)

    original_deadline = packlib.LAND_DEADLINE
    try:
        packlib.LAND_DEADLINE = 0.3
        client = SlowClient(2.0)
        store = packlib.PackStore("fieldpack:t4", client, root=root)
        started = _time.time()
        landed, waiting = store.write_many([PERSON, JOB, PAY])
        elapsed = _time.time() - started
        check("jawaban tidak menunggu tulisan yang lambat", landed, False)
        check("balasannya cepat, bukan dua puluh detik", elapsed < 1.5, True)
        check("barisnya tetap di antrean", store.queued(), 3)
        check("outbox ditutup sebentar supaya tidak dobel",
              store.retry_after(), packlib.ABANDON_COOLDOWN)
        check("flusher menghormati penutupan itu",
              store.flush(tries=1)[1], packlib.ABANDON_COOLDOWN)
        check("dan tidak mengirim apa pun selama itu", client.writes, 0)
        _time.sleep(2.2)     # the abandoned attempt finishes on its own
        check("percobaan yang ditinggal tetap mendarat sendiri", client.writes, 1)
        check("dan mengosongkan antreannya", store.queued(), 0)
        check("saldonya benar tanpa menunggu apa-apa lagi",
              store.state()["people"]["budi"]["balance"], 150000)

        # A row that arrives while a write is still in the air must survive that
        # write landing. Emptying the outbox on success used to take it along, and
        # the row had never been sent anywhere.
        client = SlowClient(1.5)
        store = packlib.PackStore("fieldpack:t5", client, root=root)
        store.write_many(["baris lama #k:pack #pk:t5 #at:2026-09-24T09:00:00"])
        check("percobaan pertama masih di udara", store.queued(), 1)
        store.write_many(["baris baru #k:pack #pk:t5 #at:2026-09-24T09:01:00"])
        check("baris baru ikut masuk antrean", store.queued(), 2)
        _time.sleep(2.0)
        check("yang mendarat cuma meninggalkan baris yang belum terkirim",
              [r["text"].split(" #")[0] for r in store.pending()], ["baris baru"])
        check("kedua baris tetap ada di salinan lokal", len(store.journal()), 2)
        # A hold has to end. The file used to store how long the hold lasted, and
        # since nothing rewrites it, the outbox read "wait 60 seconds" forever:
        # once a single write was abandoned, that pack never landed anything
        # again and the queue grew without a word. Exactly what happened to the
        # live notebook, where 51 lines sat waiting for a cooldown from the day
        # before.
        check("penutupan itu punya batas waktu", store.retry_after() > 0, True)
        stale = packlib.PackStore("fieldpack:t6", FakeClient(), root=root)
        stale.write_many(["baris tertahan #k:pack #pk:t6 #at:2026-09-24T09:00:00"])
        with open(stale.pending_path + ".retry", "w", encoding="utf-8") as fh:
            fh.write("60")            # what the old code left behind
        check("penutupan basi tidak menahan selamanya", stale.retry_after(), 0)
        check("dan outbox-nya bisa mendarat lagi",
              stale.flush(tries=1)[0] and stale.queued(), 0)
        with open(stale.pending_path + ".retry", "w", encoding="utf-8") as fh:
            fh.write("%.0f" % (_time.time() - 1))
        check("penutupan yang sudah lewat juga dianggap buka", stale.retry_after(), 0)

        # --- a relay that refuses every read ----------------------------------
        # Measured live: the outbox filled up, the relay started refusing reads,
        # and a turn answered with "UnboundLocalError: cannot access local
        # variable 'out'". Every attempt to read had failed before the accumulator
        # existed, so the return at the end of the loop had nothing to return. The
        # local copy was sitting right there the whole time.

        class DeafClient(FakeClient):
            def recall(self, query, limit, namespace, max_distance):
                raise RuntimeError("429 rate limit exceeded")

        deaf = packlib.PackStore("fieldpack:t7", DeafClient(), root=root)
        deaf.write_many([PERSON, JOB, PAY])
        try:
            read_back = deaf.lines(patient=False)
            check("relay yang menolak semua bacaan tidak meledak", read_back, [])
            check("dan salinannya tetap kebaca dari lokal",
                  deaf.state()["people"]["budi"]["balance"], 150000)
        except UnboundLocalError as exc:
            check("relay yang menolak semua bacaan tidak meledak", repr(exc), [])
    finally:
        packlib.LAND_DEADLINE = original_deadline
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
if FAILS:
    print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
    sys.exit(1)
print("all store tests passed")
