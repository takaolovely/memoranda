"""Jalankan quick tunnel Memoranda sambil mencatat URL-nya.

URL quick tunnel berubah tiap kali proses ini hidup, jadi link yang dipegang
orang selalu basi. Proses ini yang tahu URL barunya paling dulu, jadi dia yang
menuliskannya ke data/tunnel_url.txt dan mengabarkannya lewat Telegram. Kalau
tidak, satu-satunya cara tahu link baru adalah bertanya ke gw, dan itu bikin
Caligula nunggu.

Jalan di bawah systemd, jadi keluar sendiri bukan pilihan: kalau tunnel mati,
yang mati bukan cuma link, tapi seluruh jendela juri ke buku-bukunya.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
URL_PATH = os.path.join(HERE, "data", "tunnel_url.txt")
TARGET = os.environ.get("MEMORANDA_TUNNEL_TARGET", "http://127.0.0.1:8770")
OWNER_CHAT = os.environ.get("MEMORANDA_OWNER_CHAT", "").strip()
PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def owner_chat():
    """Chat yang dikabari kalau link-nya ganti.

    Dibaca dari data/bindings.json, bukan ditulis di file ini: id chat itu
    identitas orang, dan file ini ikut ke repo publik. Yang dipakai chat Telegram
    yang paling akhir disambungkan, karena itu chat yang paling baru dipakai.
    """
    if OWNER_CHAT:
        return OWNER_CHAT
    try:
        rows = json.loads(pathlib.Path(HERE, "data", "bindings.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    chats = [key.split(":", 1)[1] for key, meta in rows.items()
             if str(meta.get("channel")) == "tg" and ":" in key]
    return chats[-1] if chats else ""


def bot_token():
    """Token dari .env. Tidak pernah dicetak, tidak ditulis di file ini."""
    try:
        for line in pathlib.Path(ENV_PATH).read_text(encoding="utf-8").splitlines():
            if "TOKEN" in line.upper() and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def tell(url):
    """Kirim link baru ke Telegram, supaya tidak perlu ada yang menanyakan."""
    token = bot_token()
    chat = owner_chat()
    if not token or not chat:
        return
    text = ("Link Memoranda baru. Yang lama sudah mati.\n\n%s\n\n"
            "Ini kejadian tiap tunnel hidup ulang, jadi bookmark yang ini "
            "sampai ada kabar berikutnya." % url)
    body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % token, data=body)
    try:
        urllib.request.urlopen(req, timeout=25).read()
        print("[tunnel] link baru dikabarkan lewat telegram", flush=True)
    except Exception as exc:  # noqa: BLE001
        print("[tunnel] gagal mengabarkan: %s" % exc, flush=True)


def main():
    cmd = ["cloudflared", "tunnel", "--url", TARGET, "--no-autoupdate"]
    print("[tunnel] mulai: %s" % " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    seen = ""
    try:
        for line in proc.stdout:
            print(line.rstrip(), flush=True)
            found = PATTERN.search(line)
            if not found:
                continue
            url = found.group(0)
            if url == seen:
                continue
            seen = url
            pathlib.Path(URL_PATH).write_text(url + "\n", encoding="utf-8")
            print("[tunnel] URL: %s" % url, flush=True)
            tell(url)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
