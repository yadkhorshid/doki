"""Checks GitHub for a newer doki release."""

import json
import re
import ssl
import urllib.request

from . import __version__

RELEASES_URL = "https://api.github.com/repos/yadkhorshid/doki/releases/latest"


def parse_version(text):
    """"v2.1.0" -> (2, 1, 0); anything without numbers sorts as (0, 0, 0)."""
    numbers = [int(number) for number in re.findall(r"\d+", text or "")[:3]]
    return tuple(numbers + [0] * (3 - len(numbers)))


def ssl_context():
    # python.org builds on macOS ship without system certificates, so prefer certifi's bundle.
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def check_for_update(timeout=5):
    """Returns (version, release page URL) when a newer release exists; None otherwise or when offline."""
    request = urllib.request.Request(
        RELEASES_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"doki/{__version__}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            release = json.load(response)
    except (OSError, ValueError):
        return None
    tag = release.get("tag_name", "")
    if release.get("draft") or release.get("prerelease") or parse_version(tag) <= parse_version(__version__):
        return None
    return tag.lstrip("v"), release.get("html_url") or f"https://github.com/yadkhorshid/doki/releases/tag/{tag}"
