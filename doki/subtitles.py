"""Subtitle detection, conversion and selection."""

import os
import re
import tempfile
import time
from urllib.parse import urlsplit


# ISO 639-1 code -> (name, other spellings: ISO 639-2 codes and native names).
# Two-letter codes are only trusted in language tags and file names, since short
# tokens like "id" or "it" show up in URLs all the time.
LANGUAGES = {
    "en": ("English", ("eng", "english")),
    "es": ("Spanish", ("spa", "spanish", "español", "espanol", "castellano", "latino")),
    "pt": ("Portuguese", ("por", "portuguese", "português", "portugues")),
    "fr": ("French", ("fre", "fra", "french", "français", "francais")),
    "de": ("German", ("ger", "deu", "german", "deutsch")),
    "it": ("Italian", ("ita", "italian", "italiano")),
    "ru": ("Russian", ("rus", "russian", "русский")),
    "ar": ("Arabic", ("ara", "arabic", "العربية")),
    "ja": ("Japanese", ("jpn", "japanese", "日本語")),
    "ko": ("Korean", ("kor", "korean", "한국어")),
    "zh": ("Chinese", ("chi", "zho", "chinese", "中文")),
    "id": ("Indonesian", ("ind", "indonesian", "indonesia")),
    "ms": ("Malay", ("msa", "malay", "melayu")),
    "th": ("Thai", ("tha", "thai")),
    "vi": ("Vietnamese", ("vie", "vietnamese", "tiếng việt")),
    "tr": ("Turkish", ("tur", "turkish", "türkçe")),
    "pl": ("Polish", ("pol", "polish", "polski")),
    "nl": ("Dutch", ("dut", "nld", "dutch", "nederlands")),
    "sv": ("Swedish", ("swe", "swedish", "svenska")),
    "da": ("Danish", ("dan", "danish", "dansk")),
    "no": ("Norwegian", ("nob", "norwegian", "norsk")),
    "fi": ("Finnish", ("finnish", "suomi")),
    "hi": ("Hindi", ("hin", "hindi")),
    "uk": ("Ukrainian", ("ukr", "ukrainian")),
    "he": ("Hebrew", ("heb", "hebrew")),
    "fa": ("Persian", ("fas", "persian", "farsi")),
    "ku": ("Kurdish", ("kur", "kurdish", "kurdî", "کوردی")),
    "ro": ("Romanian", ("rum", "ron", "romanian", "română")),
    "cs": ("Czech", ("cze", "ces", "czech", "čeština")),
    "hu": ("Hungarian", ("hun", "hungarian", "magyar")),
    "el": ("Greek", ("gre", "ell", "greek")),
    "tl": ("Filipino", ("fil", "tgl", "filipino", "tagalog")),
}


def normalize_language(tag):
    """Maps a language tag such as "en-US", "spa" or "Español" to an ISO 639-1 code, or None."""
    tag = (tag or "").strip().lower()
    if not tag:
        return None
    primary = re.split(r"[-_]", tag)[0]
    for code, (name, aliases) in LANGUAGES.items():
        if primary == code or primary in aliases or tag in aliases or tag == name.lower():
            return code
    return None


def language_from_text(text):
    """Finds a language name or three-letter code in free text such as a track label or URL."""
    lowered = (text or "").lower()
    tokens = set(re.findall(r"[^\W\d_]+", lowered))
    for code, (name, aliases) in LANGUAGES.items():
        if name.lower() in tokens or any(alias in tokens or (" " in alias and alias in lowered) for alias in aliases):
            return code
    return None


def language_from_filename(url):
    """Reads two-letter codes from names like ep7.es.vtt, subs_pt-BR.srt or /fr/ep7.vtt."""
    segments = [segment for segment in urlsplit(url).path.lower().split("/") if segment]
    if not segments:
        return None
    stem = segments[-1].rsplit(".", 1)[0]
    tokens = [token for token in re.split(r"[^a-z]+", stem) if token]
    # Only the folder holding the file counts; "id" there is too often a record ID.
    parent = segments[-2] if len(segments) > 1 and segments[-2] != "id" else ""
    candidates = tokens[-2:] + ([parent] if len(parent) <= 5 else [])
    for candidate in candidates:
        if len(candidate) == 2 and candidate in LANGUAGES:
            return candidate
        if len(candidate) == 5 and candidate[2] in "-_" and candidate[:2] in LANGUAGES:
            return candidate[:2]
    return None


def detect_subtitle_language(url, headers=None, label="", srclang=""):
    """Best guess at a subtitle's language as an ISO 639-1 code, or None when unknown."""
    headers = headers or {}
    for tag in (srclang, headers.get("content-language", "")):
        code = normalize_language(tag)
        if code:
            return code
    hint = f"{label} {url} {headers.get('content-disposition', '')}"
    return language_from_text(hint) or language_from_filename(url)


def language_name(code):
    return LANGUAGES[code][0] if code in LANGUAGES else "Unknown language"


def mpv_language_tags(code, tag=""):
    """Tags for mpv's --slang: the playlist's own tag first, then the two- and three-letter codes."""
    tags = [tag] if tag else []
    if code in LANGUAGES:
        tags.append(code)
        tags.extend(alias for alias in LANGUAGES[code][1] if len(alias) == 3 and alias.isascii())
    return list(dict.fromkeys(tags))


def is_english_subtitle(url, headers):
    content_type = headers.get("content-type", "").lower()
    is_subtitle = is_direct_subtitle_url(url)
    is_subtitle = is_subtitle or any(
        kind in content_type
        for kind in ("text/vtt", "application/x-subrip", "application/ttml+xml")
    )
    return is_subtitle and detect_subtitle_language(url, headers) == "en"


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


TEMP_SUBTITLE_PREFIX = "open-in-mpv-"


def remove_stale_subtitles(max_age_hours=12):
    """Deletes temporary subtitles left behind if doki closed before mpv did."""
    cutoff = time.time() - max_age_hours * 3600
    directory = tempfile.gettempdir()
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if not name.startswith(TEMP_SUBTITLE_PREFIX):
            continue
        path = os.path.join(directory, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


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
    with tempfile.NamedTemporaryFile(prefix=TEMP_SUBTITLE_PREFIX, suffix=suffix, delete=False) as subtitle_file:
        subtitle_file.write(body)
        return subtitle_file.name


def make_subtitle_options(subtitle_candidates, hls_tracks):
    """Builds (label, selection) pairs: playlist tracks first (English leading), then captured files."""
    options = [("No subtitles", {"kind": "none", "url": None, "language": None})]
    labels = set()

    def unique(label):
        base, number = label, 2
        while label in labels:
            label = f"{base} ({number})"
            number += 1
        labels.add(label)
        return label

    def sort_key(language):
        return (language != "en", language is None, language_name(language))

    for index, track in sorted(enumerate(hls_tracks), key=lambda pair: sort_key(pair[1]["language"])):
        name = language_name(track["language"])
        if track["name"] and detect_subtitle_language("", label=track["name"]) != track["language"]:
            name += f" - {track['name']}"
        options.append((unique(f"{name} (from playlist)"), {
            "kind": "playlist",
            "url": track["url"],
            "language": track["language"],
            "slang": mpv_language_tags(track["language"], track["tag"]),
            # mpv numbers subtitle tracks from 1 in playlist order; used when the language is unknown.
            "sid": index + 1,
        }))

    playlist_urls = {track["url"] for track in hls_tracks}
    languages = {}
    for subtitle_url, language in subtitle_candidates:
        if subtitle_url not in playlist_urls:
            languages[subtitle_url] = languages.get(subtitle_url) or language
    for subtitle_url, language in sorted(languages.items(), key=lambda item: sort_key(item[1])):
        filename = urlsplit(subtitle_url).path.rsplit("/", 1)[-1] or "subtitle file"
        options.append((unique(f"{language_name(language)} - {filename}"), {
            "kind": "external",
            "url": subtitle_url,
            "language": language,
            "slang": mpv_language_tags(language),
        }))
    return options


def preferred_subtitle_label(options, language):
    """The option to select for a preferred language: playlist tracks before captured files."""
    for kind in ("playlist", "external"):
        for label, selection in options:
            if selection["kind"] == kind and selection["language"] == language:
                return label
    return None
