"""Watch history, next-episode links and resume positions."""

import hashlib
import os
import re
import sys
import time
from urllib.parse import urlsplit

from .paths import data_path, load_json, save_json


RESUME_SCRIPT = """local path = mp.get_opt("doki-resume-file")
if path then
    local position, duration
    mp.observe_property("time-pos", "number", function(_, value) if value then position = value end end)
    mp.observe_property("duration", "number", function(_, value) if value then duration = value end end)
    mp.register_event("shutdown", function()
        if not position then return end
        local file = io.open(path, "w")
        if file then
            file:write(string.format("%.3f %.3f", position, duration or 0))
            file:close()
        end
    end)
end
"""
HISTORY_LIMIT = 25


def add_history_entry(page_url, title):
    history = [entry for entry in load_json("history.json", []) if entry.get("url") != page_url]
    history.insert(0, {"url": page_url, "title": title or "", "watched": time.strftime("%Y-%m-%d %H:%M")})
    save_json("history.json", history[:HISTORY_LIMIT])
    return history[:HISTORY_LIMIT]


def next_episode_url(page_url):
    parts = urlsplit(page_url)

    def bump(match):
        number = match.group(2)
        return match.group(1) + str(int(number) + 1).zfill(len(number))

    for field in ("path", "query"):
        text = getattr(parts, field)
        matches = list(re.finditer(r"(?i)(ep(?:isode)?[-_=/]?)(\d+)", text))
        if matches:
            match = matches[-1]
            text = text[:match.start()] + bump(match) + text[match.end():]
            return parts._replace(**{field: text}).geturl()
    matches = list(re.finditer(r"()(\d+)", parts.path))
    if not matches:
        return None
    match = matches[-1]
    path = parts.path[:match.start()] + bump(match) + parts.path[match.end():]
    return parts._replace(path=path).geturl()


def resume_file_path(page_url):
    key = hashlib.sha1(page_url.encode("utf-8")).hexdigest()
    os.makedirs(data_path("positions"), exist_ok=True)
    return data_path("positions", key + ".txt")


def watch_progress(page_url):
    """(position, duration) in seconds from when mpv last closed on this page, or None."""
    try:
        with open(resume_file_path(page_url), encoding="utf-8") as file:
            position, duration = (float(value) for value in file.read().split()[:2])
    except (OSError, ValueError):
        return None
    return position, duration


def is_finished(position, duration):
    return bool(duration) and position > duration - 90


def read_resume_position(page_url):
    progress = watch_progress(page_url)
    if not progress:
        return None
    position, duration = progress
    if position < 30 or is_finished(position, duration):
        return None
    return position


def remove_history_entry(page_url):
    """Forgets a page and its resume position; returns the remaining history."""
    history = [entry for entry in load_json("history.json", []) if entry.get("url") != page_url]
    save_json("history.json", history)
    try:
        os.remove(resume_file_path(page_url))
    except OSError:
        pass
    return history


def make_resume_arguments(page_url, title, start_position=None):
    script_path = data_path("doki-resume.lua")
    try:
        with open(script_path, "w", encoding="utf-8") as file:
            file.write(RESUME_SCRIPT)
    except OSError as error:
        print(f"[data] Could not write resume script: {error}", file=sys.stderr)
        return []
    args = [
        f"--script={script_path}",
        f"--script-opts=doki-resume-file={resume_file_path(page_url)}",
    ]
    if title:
        args.append(f"--force-media-title={title}")
    if start_position:
        args.append(f"--start={start_position:.0f}")
    return args


def format_timestamp(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"
