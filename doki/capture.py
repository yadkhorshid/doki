"""Opens an episode page in Chromium and records its streams and subtitles."""

import os
import re
import sys
import time


if getattr(sys, "frozen", False):
    bundled_browsers = os.path.join(os.path.dirname(sys.executable), "browsers")
    if os.path.isdir(bundled_browsers):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers

from playwright.sync_api import sync_playwright
from .subtitles import is_direct_subtitle_url, is_english_subtitle, is_subtitle_resource


def inspect_player_frame(frame):
    try:
        return frame.evaluate("""() => {
            const videos = Array.from(document.querySelectorAll('video'));
            const video = videos.find(item => item.videoWidth && item.videoHeight) || videos[0];
            if (!video) return null;
            return {
                width: video.videoWidth || 0,
                height: video.videoHeight || 0,
                subtitles: Array.from(video.querySelectorAll('track')).map(track => ({
                    url: track.src,
                    language: track.srclang,
                    label: track.label
                }))
            };
        }""")
    except Exception:
        return None


def capture_page(page_url, status_callback=None, page_info=None):
    streams = []
    stream_activity = []
    subtitle_candidates = []
    subtitle_responses = {}
    player_video_size = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        def handle_response(response):
            content_type = response.headers.get("content-type", "").lower()
            if ".m3u8" in response.url.lower() or "mpegurl" in content_type:
                try:
                    playlist_text = response.text()
                except Exception:
                    playlist_text = ""
                streams.append((
                    response.url,
                    response.request.all_headers(),
                    playlist_text,
                    response.status,
                    content_type,
                ))
                stream_activity.append(time.monotonic())
            elif is_subtitle_resource(response.url, response.headers):
                try:
                    subtitle_body = response.body()
                except Exception:
                    subtitle_body = b""
                subtitle_responses[response.url] = (
                    response.status,
                    content_type,
                    subtitle_body,
                )
                subtitle_candidates.append((
                    response.url,
                    is_english_subtitle(response.url, response.headers),
                ))

        page.on("response", handle_response)
        if status_callback:
            status_callback("Browser open. Press Play if needed; waiting for a stream (30-second limit).")
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=45_000)
        except Exception:
            pass
        capture_deadline = time.monotonic() + 30
        stream_status_sent = False
        while time.monotonic() < capture_deadline:
            page.wait_for_timeout(200)
            if not stream_activity:
                continue
            if status_callback and not stream_status_sent:
                status_callback("Stream found; collecting subtitle tracks briefly.")
                stream_status_sent = True
            if time.monotonic() - stream_activity[-1] >= 2:
                break
        for frame in page.frames:
            player_info = inspect_player_frame(frame)
            if not player_info:
                continue
            width = player_info.get("width", 0)
            height = player_info.get("height", 0)
            if width and height and not player_video_size:
                player_video_size = (width, height)
            for subtitle in player_info.get("subtitles", []):
                language = subtitle.get("language", "").lower()
                label = subtitle.get("label", "")
                is_english = language == "en" or language == "eng" or language.startswith("en-")
                is_english = is_english or re.search(r"\benglish\b", label, re.IGNORECASE) is not None
                if is_english and is_direct_subtitle_url(subtitle.get("url", "")):
                    subtitle_candidates.append((subtitle["url"], True))
        if page_info is not None:
            try:
                page_info["title"] = page.title().strip()
            except Exception:
                page_info["title"] = ""
        browser.close()

    return streams, subtitle_candidates, subtitle_responses, player_video_size
