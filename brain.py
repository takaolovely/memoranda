"""Talking to the notebook.

Every channel reaches the pack the same way the web page does: over HTTP, at
/api/turn and /api/state. Nothing here parses, counts or decides anything. That
is the point of the seam. The brain has one writer, the notebook server, and a
channel that grew its own copy of the rules would be a second brain.

`Brain` takes a base URL so the bot can run next to the server or somewhere else,
and `post` takes a timeout because a turn that writes to Walrus can be slow while
a health check should not be.
"""

import json
import urllib.error
import urllib.request


class BrainError(RuntimeError):
    pass


class Brain:
    def __init__(self, base="http://127.0.0.1:8770"):
        self.base = base.rstrip("/")

    def _call(self, path, payload=None, timeout=180):
        url = self.base + path
        try:
            if payload is None:
                req = urllib.request.Request(url)
            else:
                req = urllib.request.Request(
                    url, data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise BrainError("notebook not reachable at %s: %s" % (self.base, exc)) from exc
        except (ValueError, OSError) as exc:
            raise BrainError("%s on %s: %s" % (type(exc).__name__, path, exc)) from exc

    # ---- the four things a channel needs ---------------------------------

    def health(self, timeout=10):
        return self._call("/api/health", timeout=timeout)

    def create_pack(self, biz="ac_service", name="", lang=""):
        """A new empty book. The passkey in the reply is the only way back in."""
        return self._call("/api/pack", {"action": "create", "biz": biz,
                                        "name": name, "lang": lang})

    def enter(self, passkey):
        return self._call("/api/pack", {"action": "enter", "passkey": passkey})

    def settings(self, passkey, lang="", cur="", tz=""):
        return self._call("/api/pack", {"action": "lang", "passkey": passkey,
                                        "lang": lang, "cur": cur, "tz": tz})

    def turn(self, passkey, text, timeout=180):
        """One message in, one reply out. This is the whole product."""
        return self._call("/api/turn", {"passkey": passkey, "text": text},
                          timeout=timeout)

    def state(self, passkey, timeout=60):
        return self._call("/api/state", {"passkey": passkey}, timeout=timeout)

    def fired(self, passkey, ref, text="delivered", timeout=120):
        """Write down that a reminder was delivered, so it is not sent twice."""
        return self._call("/api/fired", {"passkey": passkey, "ref": ref,
                                         "text": text}, timeout=timeout)
