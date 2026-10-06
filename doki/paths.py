"""Bundled resource and per-user data file locations."""

import json
import os
import sys


def resource_path(*parts):
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, *parts)


def app_path(*parts):
    """Files shipped next to doki.exe (or the repo root when running from source)."""
    if getattr(sys, "frozen", False):
        root = os.path.dirname(sys.executable)
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *parts)


def data_path(*parts):
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    directory = os.path.join(base, "doki")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, *parts)


def load_json(name, default):
    try:
        with open(data_path(name), encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return default


def save_json(name, value):
    try:
        with open(data_path(name), "w", encoding="utf-8") as file:
            json.dump(value, file, indent=2)
    except OSError as error:
        print(f"[data] Could not save {name}: {error}", file=sys.stderr)
