"""Opens an episode page in Chromium and records its streams and subtitles."""

import os
import sys
import time

from .paths import app_path


if getattr(sys, "frozen", False):
    bundled_browsers = app_path("browsers")
    if os.path.isdir(bundled_browsers):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers

from playwright.sync_api import sync_playwright
from .adblock import block_ads
from .subtitles import detect_subtitle_language, is_direct_subtitle_url, is_subtitle_resource


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


PLAY_VIDEOS_SCRIPT = """() => {
    for (const video of document.querySelectorAll('video')) {
        video.muted = true;
        video.play().catch(() => {});
    }
}"""


def capture_page(page_url, status_callback=None, page_info=None):
    """Captures in a hidden browser first, then in a visible one if nothing was found."""
    with sync_playwright() as p:
        if status_callback:
            status_callback("Looking for the stream in the background...")
        result = capture_once(p, page_url, None, page_info, headless=True, timeout=20)
        if result[0]:
            return result
        if status_callback:
            status_callback("Couldn't find it in the background. Press Play in the browser if needed (30-second limit).")
        return capture_once(p, page_url, status_callback, page_info, headless=False, timeout=30)


def capture_once(p, page_url, status_callback, page_info, headless, timeout):
    streams = []
    stream_activity = []
    subtitle_candidates = []
    subtitle_responses = {}
    player_video_size = None
    browser = p.chromium.launch(
        headless=headless,
        # The full Chromium build in new headless mode looks like a normal browser to most players.
        channel="chromium" if headless else None,
        args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
    )
    try:
        context = browser.new_context()
        block_ads(context)
        page = context.new_page()

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
                    detect_subtitle_language(response.url, response.headers),
                ))

        page.on("response", handle_response)
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=45_000)
        except Exception:
            pass
        capture_deadline = time.monotonic() + timeout
        next_play_attempt = 0
        stream_status_sent = False
        while time.monotonic() < capture_deadline:
            page.wait_for_timeout(200)
            if not stream_activity:
                if time.monotonic() >= next_play_attempt:
                    next_play_attempt = time.monotonic() + 2
                    for frame in page.frames:
                        try:
                            frame.evaluate(PLAY_VIDEOS_SCRIPT)
                        except Exception:
                            pass
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
                subtitle_url = subtitle.get("url", "")
                if is_direct_subtitle_url(subtitle_url):
                    subtitle_candidates.append((subtitle_url, detect_subtitle_language(
                        subtitle_url, label=subtitle.get("label", ""), srclang=subtitle.get("language", ""),
                    )))
        if page_info is not None:
            try:
                page_info["title"] = page.title().strip()
            except Exception:
                page_info["title"] = ""
    finally:
        browser.close()

    return streams, subtitle_candidates, subtitle_responses, player_video_size
