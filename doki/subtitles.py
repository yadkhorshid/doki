"""Subtitle detection, conversion and selection."""

import re
import tempfile
from urllib.parse import urlsplit


def is_english_subtitle(url, headers):
    content_type = headers.get("content-type", "").lower()
    disposition = headers.get("content-disposition", "")
    is_subtitle = is_direct_subtitle_url(url)
    is_subtitle = is_subtitle or any(
        kind in content_type
        for kind in ("text/vtt", "application/x-subrip", "application/ttml+xml")
    )
    if not is_subtitle:
        return False

    language = headers.get("content-language", "")
    hint = f"{url} {disposition} {language}"
    return re.search(r"(?:^|[^a-z])(?:en|eng|english)(?:$|[^a-z])", hint, re.IGNORECASE) is not None


def is_subtitle_resource(url, headers):
    if is_direct_subtitle_url(url):
        return True
    content_type = headers.get("content-type", "").lower()
    return any(kind in content_type for kind in (
        "text/vtt",
        "application/x-subrip",
        "application/srt",
        "application/ttml+xml",
        "text/x-ssa",
        "application/ass",
    ))


def is_direct_subtitle_url(url):
    return re.search(r"\.(?:vtt|srt|ass|ssa)(?:$|[?#])", url, re.IGNORECASE) is not None


def webvtt_to_srt(body):
    lines = body.decode("utf-8-sig", errors="replace").splitlines()
    cues = []
    index = 0

    def timestamp_to_srt(timestamp):
        match = re.fullmatch(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})", timestamp)
        if not match:
            return None
        hours, minutes, seconds, milliseconds = match.groups()
        return f"{int(hours or 0):02}:{minutes}:{seconds},{milliseconds}"

    while index < len(lines):
        line = lines[index].strip()
        if not line or line.startswith("WEBVTT"):
            index += 1
            continue
        if line.startswith(("NOTE", "STYLE", "REGION")):
            while index < len(lines) and lines[index].strip():
                index += 1
            continue
        if "-->" not in line:
            if index + 1 < len(lines) and "-->" in lines[index + 1]:
                index += 1
            else:
                index += 1
                continue

        start_text, end_text = line.split("-->", 1)
        start = timestamp_to_srt(start_text.strip())
        end = timestamp_to_srt(end_text.strip().split()[0])
        index += 1
        cue_lines = []
        while index < len(lines) and lines[index].strip():
            cue_lines.append(lines[index])
            index += 1
        if start and end and cue_lines:
            cue_number = len(cues) + 1
            cues.append(f"{cue_number}\n{start} --> {end}\n" + "\n".join(cue_lines))

    return ("\n\n".join(cues) + "\n").encode("utf-8") if cues else None


def save_captured_subtitle(url, response):
    if not response:
        return None
    status, _, body = response
    if not 200 <= status < 300 or not body:
        return None

    suffix = urlsplit(url).path.rsplit(".", 1)
    suffix = "." + suffix[-1] if len(suffix) == 2 else ".vtt"
    if suffix.lower() == ".vtt":
        if not body.decode("utf-8-sig", errors="replace").lstrip().startswith("WEBVTT"):
            return None
        body = webvtt_to_srt(body)
        if not body:
            return None
        suffix = ".srt"
    with tempfile.NamedTemporaryFile(prefix="open-in-mpv-", suffix=suffix, delete=False) as subtitle_file:
        subtitle_file.write(body)
        return subtitle_file.name


def make_subtitle_options(subtitle_candidates, hls_subtitles):
    options = [("No subtitles", {"kind": "none", "url": None})]
    if hls_subtitles:
        options.append(("English subtitles from playlist", {"kind": "playlist", "url": None}))

    languages = {}
    for subtitle_url, is_english in subtitle_candidates:
        if subtitle_url not in hls_subtitles:
            languages[subtitle_url] = languages.get(subtitle_url, False) or is_english
    for subtitle_url, is_english in languages.items():
        filename = urlsplit(subtitle_url).path.rsplit("/", 1)[-1] or "subtitle file"
        language = "English" if is_english else "Unverified"
        options.append((f"{language} - {filename}", {
            "kind": "external",
            "url": subtitle_url,
            "english": is_english,
        }))
    return options
