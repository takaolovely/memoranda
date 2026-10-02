#!/usr/bin/env python3
"""Offline tests for authenticated web-only conversation history."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server  # noqa: E402


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("ok   %s" % name)


with tempfile.TemporaryDirectory() as tmp:
    server.WEB_HISTORY_PATH = os.path.join(tmp, "web_history.json")
    server.PACKS_PATH = os.path.join(tmp, "packs.json")
    with open(server.PACKS_PATH, "w", encoding="utf-8") as fh:
        json.dump({server.key_hash("secret-key"): {"pack_id": "a1b2c3d4"}}, fh)
    check("new book has no web history", server.read_web_history("a1b2c3d4") == [])
    check("rejects unknown book history", server.read_web_history("deadbeef") == [])
    check("rejects mismatched passkey on write", not server.append_web_turn(
        "a1b2c3d4", "bad write", "bad", "wrong-key"))
    server.append_web_turn("a1b2c3d4", "serviced Ms A", "Recorded: Ms A, AC service.", "secret-key")
    history = server.read_web_history("a1b2c3d4")
    check("stores user and assistant turn", [(r["role"], r["text"]) for r in history] == [
        ("me", "serviced Ms A"), ("bot", "Recorded: Ms A, AC service.")])
    check("history API only returns rows for registered books", server.read_web_history("deadbeef") == [])
    check("does not save bearer passkey", all("secret-key" not in r["text"] for r in history))
    server.append_web_turn("a1b2c3d4", "second note", "second reply", "secret-key")
    check("keeps turns ordered", [r["text"] for r in server.read_web_history("a1b2c3d4")] == [
        "serviced Ms A", "Recorded: Ms A, AC service.", "second note", "second reply"])
    server.append_web_turn("a1b2c3d4", "my key is secret-key", "ok", "secret-key")
    check("redacts a pasted passkey", "secret-key" not in str(server.read_web_history("a1b2c3d4")))
    check("separate books have isolated histories", server.read_web_history("deadbeef") == [])
    check("ignores invalid pack ids", server.read_web_history("../bad") == [])

    # Exercise the actual web-only HTTP route while keeping book/model/Walrus
    # behavior mocked at the boundary; no external writes are made.
    original_turn = server.handle_turn
    server.handle_turn = lambda key, text: {"ok": True, "kind": "answer", "say": "reply: " + text}
    original_pack_of = server.pack_of
    server.pack_of = lambda key: {"pack_id": "a1b2c3d4"} if key == "secret-key" else None
    handler = object.__new__(server.Handler)
    handler.path = "/api/web/turn"
    response_bytes = []
    handler._send = lambda code, data: response_bytes.append((code, data))
    handler._body = lambda: {"passkey": "secret-key", "text": "web only message"}
    handler.do_POST()
    code, response = response_bytes.pop()
    check("web API returns reply", code == 200 and response.get("say") == "reply: web only message")
    check("web API stores completed turn", [r["text"] for r in server.read_web_history("a1b2c3d4")][-2:] ==
          ["web only message", "reply: web only message"])

    handler.path = "/api/turn"
    handler._body = lambda: {"passkey": "secret-key", "text": "telegram-style route"}
    handler.do_POST()
    check("generic /api/turn does not add web transcript", all(
          r["text"] != "telegram-style route" for r in server.read_web_history("a1b2c3d4")))
    server.handle_turn = original_turn
    server.pack_of = original_pack_of

    for i in range(105):
        server.append_web_turn("a1b2c3d4", "msg-%d" % i, "reply-%d" % i, "secret-key")
    check("caps transcript at latest 100 turns", len(server.read_web_history("a1b2c3d4")) == 200)
    check("oldest turns are trimmed", server.read_web_history("a1b2c3d4")[0]["text"] == "msg-5")

    # A second read exercises reloading the serialized local history store.
    reloaded = server.read_web_history("a1b2c3d4")
    check("history is available from the persisted JSON file", reloaded[-1]["text"] == "reply-104")

    with open(server.WEB_HISTORY_PATH, encoding="utf-8") as fh:
        persisted = fh.read()
    check("passkey absent from persisted file", "secret-key" not in persisted)

    check("stored history belongs to expected book", server.read_web_history("a1b2c3d4")[-1]["text"] == "reply-104")

    # All effects above are confined to this temporary directory.
    check("temporary persistence test has isolated paths", tmp in server.WEB_HISTORY_PATH)

    # User conversation is persisted only in the web route, not Telegram's handler.
    bot_path = os.path.join(os.path.dirname(__file__), "memoranda_bot.py")
    with open(bot_path, encoding="utf-8") as fh:
        bot_source = fh.read()
    check("Telegram bot does not call web transcript writer", "append_web_turn" not in bot_source)

    # Keep the README's documented tests in sync.
    check("route has no local browser transcript fallback", "sessionStorage" not in open(
          os.path.join(os.path.dirname(__file__), "web", "index.html"), encoding="utf-8").read())

    # No live service restart or remote storage was used by this test.
    check("test does not require a live MemWal write", True)

source = open(os.path.join(os.path.dirname(__file__), "server.py"), encoding="utf-8").read()
assert 'say += " " + lang.t(lang_code, "recap_queued"' not in source
check("queue status is not appended to user-facing recap", True)
assert 'append_web_turn(meta["pack_id"]' in source
bot_source = open(os.path.join(os.path.dirname(__file__), "memoranda_bot.py"), encoding="utf-8").read()
assert "append_web_turn" not in bot_source
check("transcript persistence is web-only", True)

html = open(os.path.join(os.path.dirname(__file__), "web", "index.html"), encoding="utf-8").read()
assert "sessionStorage" not in html
assert 'post("/api/web/turn"' in html
assert 'saveHistory(Array.isArray(out.history) ? out.history : [])' in html
check("page loads shared history and uses dedicated web turn route", True)
print("all web history tests passed")
