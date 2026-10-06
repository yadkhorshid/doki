"""Checks a build before release: bundled mpv and shaders, helpers, and a hidden-browser capture.

Run from the repo root after build.ps1 or build-macos.sh: python tests/smoke_test.py
"""

import functools
import http.server
import os
import subprocess
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from doki import anime4k, capture, mpv  # noqa: E402
from doki.adblock import AD_URL_PATTERN  # noqa: E402
from doki.library import next_episode_url  # noqa: E402


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def check(condition, message):
    if not condition:
        raise SystemExit(f"FAILED: {message}")
    print(f"ok: {message}")


def main():
    executable = mpv.bundled_mpv_executable()
    check(executable is not None, "bundled mpv is present")
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=120)
    check(version.stdout.startswith("mpv "), f"bundled mpv runs ({version.stdout.splitlines()[0] if version.stdout else version.stderr.strip()})")
    check(mpv.find_mpv_executable() == executable, "doki prefers the bundled mpv")
    check(anime4k.shaders_available(), "Anime4K shaders are bundled")
    check(next_episode_url("https://x.tv/show/ep-09") == "https://x.tv/show/ep-10", "next episode link")
    check(AD_URL_PATTERN.match("https://ads.exoclick.com/x.js") is not None, "ad hosts are blocked")

    handler = functools.partial(QuietHandler, directory=os.path.join(ROOT, "tests", "fixtures"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        page_info = {}
        streams, _, _, _ = capture.capture_page(
            f"http://127.0.0.1:{server.server_port}/episode.html", print, page_info,
        )
    finally:
        server.shutdown()
    check(bool(streams), "hidden browser captured the HLS stream")
    check(page_info.get("title") == "Test Episode 7", "page title captured")


if __name__ == "__main__":
    main()
