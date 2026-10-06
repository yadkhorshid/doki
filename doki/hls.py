"""HLS playlist parsing."""

import re
from urllib.parse import urljoin

from .subtitles import detect_subtitle_language


def parse_hls_playlist(playlist_url, playlist_text):
    qualities = set()
    english_subtitles = []

    for line in playlist_text.splitlines():
        if line.startswith("#EXT-X-STREAM-INF:"):
            match = re.search(r"RESOLUTION=\d+x(\d+)", line)
            if match:
                qualities.add(int(match.group(1)))
        elif line.startswith("#EXT-X-MEDIA:"):
            attributes = {
                key: quoted or unquoted
                for key, quoted, unquoted in re.findall(
                    r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', line.partition(":")[2]
                )
            }
            if attributes.get("TYPE") != "SUBTITLES":
                continue
            language = attributes.get("LANGUAGE", "").lower()
            name = attributes.get("NAME", "")
            is_english = language == "eng" or language.startswith("en-") or language == "en"
            is_english = is_english or re.search(r"\benglish\b", name, re.IGNORECASE) is not None
            if is_english and attributes.get("URI"):
                english_subtitles.append(urljoin(playlist_url, attributes["URI"]))

    return sorted(qualities), english_subtitles


def parse_hls_subtitle_tracks(playlist_url, playlist_text):
    """Every subtitle rendition in a master playlist, with its detected language."""
    tracks = []
    for line in playlist_text.splitlines():
        if not line.startswith("#EXT-X-MEDIA:"):
            continue
        attributes = {
            key: quoted or unquoted
            for key, quoted, unquoted in re.findall(
                r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', line.partition(":")[2]
            )
        }
        if attributes.get("TYPE") != "SUBTITLES" or not attributes.get("URI"):
            continue
        url = urljoin(playlist_url, attributes["URI"])
        name = attributes.get("NAME", "")
        tag = attributes.get("LANGUAGE", "")
        tracks.append({
            "url": url,
            "tag": tag,
            "name": name,
            "language": detect_subtitle_language(url, label=name, srclang=tag),
        })
    return tracks


def parse_hls_variants(playlist_url, playlist_text):
    variants = []
    lines = playlist_text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attributes = {
            key: quoted or unquoted
            for key, quoted, unquoted in re.findall(
                r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', line.partition(":")[2]
            )
        }
        variant_uri = next(
            (candidate.strip() for candidate in lines[index + 1:] if candidate.strip() and not candidate.startswith("#")),
            None,
        )
        if not variant_uri:
            continue
        resolution = re.search(r"RESOLUTION=\d+x(\d+)", line)
        height = int(resolution.group(1)) if resolution else None
        try:
            bandwidth = int(attributes.get("BANDWIDTH") or attributes.get("AVERAGE-BANDWIDTH"))
        except (TypeError, ValueError):
            bandwidth = None
        label = f"{height}p" if height else "Unknown resolution"
        if bandwidth:
            label += f" ({bandwidth / 1_000_000:.1f} Mbps)"
        variants.append({
            "label": label,
            "url": urljoin(playlist_url, variant_uri),
            "height": height,
            "bandwidth": bandwidth,
        })
    return variants


def make_quality_options(playlist_url, playlist_text):
    options = [("Auto (mpv default)", None)]
    variants = parse_hls_variants(playlist_url, playlist_text)
    if variants:
        options.append(("Highest available", "max"))
    for index, variant in enumerate(variants, start=1):
        if variant["bandwidth"]:
            label = variant["label"]
            if sum(item[0] == label for item in options) > 0:
                label = f"{label} - variant {index}"
            options.append((label, variant["bandwidth"]))
    return options
