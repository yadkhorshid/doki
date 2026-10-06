"""Console mode (doki --cli)."""

from urllib.parse import urlsplit

from .capture import capture_page
from .hls import parse_hls_playlist
from .mpv import find_mpv_executable, launch_in_new_powershell, make_mpv_arguments, make_mpv_command
from .subtitles import save_captured_subtitle


def console_main():
    page_url = input("Paste the anime episode or player URL: ").strip()
    if not page_url:
        print("No URL provided.")
        return

    try:
        streams, subtitle_candidates, subtitle_responses, player_video_size = capture_page(page_url, print)
    except Exception as error:
        print(f"Browser capture failed: {error}")
        return

    if not streams:
        print("No HLS playlist was detected. Try an episode/player URL and press Play in the browser window.")
        return

    stream_url, headers, playlist_text, status, content_type = max(
        streams,
        key=lambda item: ("#EXT-X-STREAM-INF:" in item[2], len(item[2])),
    )
    qualities, hls_subtitles = parse_hls_playlist(stream_url, playlist_text)
    candidate_languages = {}
    for subtitle_url, language in subtitle_candidates:
        if subtitle_url not in hls_subtitles:
            candidate_languages[subtitle_url] = candidate_languages.get(subtitle_url, False) or language == "en"

    english_subtitles = [url for url, is_english in candidate_languages.items() if is_english]
    unknown_subtitles = [url for url, is_english in candidate_languages.items() if not is_english]
    standalone_subtitles = english_subtitles[:1]
    subtitle_language_unverified = False
    if not standalone_subtitles and len(unknown_subtitles) == 1:
        standalone_subtitles = unknown_subtitles
        subtitle_language_unverified = True
    subtitle_source_url = standalone_subtitles[0] if standalone_subtitles else None
    subtitle_file = save_captured_subtitle(
        subtitle_source_url, subtitle_responses.get(subtitle_source_url)
    ) if subtitle_source_url else None
    if subtitle_file:
        standalone_subtitles = [subtitle_file]

    print("\nM3U8 URL:")
    print(stream_url)
    is_hls_manifest = playlist_text.lstrip().startswith("#EXTM3U")
    print(f"Playlist response: HTTP {status}, {content_type or 'unknown content type'}")
    print(f"Valid HLS manifest: {'yes' if is_hls_manifest else 'no'}")
    if player_video_size:
        width, height = player_video_size
        print(f"\nVideo quality: {height}p ({width}x{height}, detected in browser)")
    elif qualities:
        quality_labels = [f"{height}p" for height in sorted(qualities, reverse=True)]
        print(f"\nVideo quality: {quality_labels[0]} (highest available)")
        print("Available qualities: " + ", ".join(quality_labels))
    else:
        print("\nVideo quality: not listed in the HLS playlist")
    if qualities and player_video_size:
        quality_labels = [f"{height}p" for height in sorted(qualities, reverse=True)]
        print("Available qualities: " + ", ".join(quality_labels))

    if hls_subtitles:
        print("English subtitles: available in the HLS playlist; mpv will prefer English.")
    elif standalone_subtitles and subtitle_language_unverified:
        print("Subtitle file detected and included; its language could not be verified as English.")
    elif standalone_subtitles:
        print("English subtitle file detected and included in the command.")
    elif len(unknown_subtitles) > 1:
        print(f"Found {len(unknown_subtitles)} subtitle responses, but could not safely identify a complete English track.")
    else:
        print("English subtitles: none detected; mpv will prefer English if the playlist provides it.")
    if standalone_subtitles and subtitle_file:
        status, response_type, _ = subtitle_responses[subtitle_source_url]
        conversion = " (converted from WebVTT to SubRip)" if urlsplit(subtitle_source_url).path.lower().endswith(".vtt") else ""
        print(f"Subtitle response: HTTP {status}, {response_type or 'unknown content type'}; saved locally{conversion} as {subtitle_file}")
    elif standalone_subtitles:
        subtitle_response = subtitle_responses.get(subtitle_source_url)
        if subtitle_response:
            status, response_type, _ = subtitle_response
            print(f"Subtitle response: HTTP {status}, {response_type or 'unknown content type'}; browser could not save its body.")

    mpv_executable = find_mpv_executable()
    if not mpv_executable:
        print("mpv was not found. Install mpv and add it to PATH, or register mpv.exe with Windows.")
        return
    launch_executable, launch_arguments = make_mpv_arguments(
        stream_url,
        headers,
        page_url,
        standalone_subtitles,
        mpv_executable,
        debug=True,
    )
    command = make_mpv_command(
        stream_url,
        headers,
        page_url,
        standalone_subtitles,
        mpv_executable,
        debug=True,
    )
    print("\nmpv command:")
    print(command)
    if headers.get("cookie"):
        print("\nThe command includes a session cookie. Keep it private; it may grant access to your account.")
    try:
        cleanup_paths = [subtitle_file] if subtitle_file else []
        debug_messages = [
            f"[subtitle-debug] HLS English tracks detected: {len(hls_subtitles)}",
            f"[subtitle-debug] external subtitle candidates detected: {len(candidate_languages)}",
            f"[subtitle-debug] selected subtitle source: {'external' if standalone_subtitles else 'HLS playlist' if hls_subtitles else 'none'}",
        ]
        if launch_in_new_powershell(
            command,
            cleanup_paths,
            debug_messages,
            launch_executable,
            launch_arguments,
        ):
            print("Started mpv in a new PowerShell window.")
        else:
            print("Could not open PowerShell automatically; run the command above manually.")
    except OSError as error:
        print(f"Could not launch mpv automatically: {error}")
