import base64
import ctypes
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from urllib.parse import urljoin, urlsplit
from tkinter import messagebox, ttk

if getattr(sys, "frozen", False):
    bundled_browsers = os.path.join(os.path.dirname(sys.executable), "browsers")
    if os.path.isdir(bundled_browsers):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers

from playwright.sync_api import sync_playwright


def resource_path(*parts):
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *parts)


def powershell_quote(value):
    escaped = value.replace("`", "``").replace('"', '`"').replace("$", "`$")
    return '"' + escaped + '"'


def find_mpv_executable():
    for name in ("mpv.exe", "mpv"):
        executable = shutil.which(name)
        if executable:
            return executable
    if os.name != "nt":
        return None

    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(
                hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\mpv.exe"
            ) as key:
                executable, _ = winreg.QueryValueEx(key, None)
        except OSError:
            continue
        executable = os.path.expandvars(executable.strip('"'))
        if os.path.isfile(executable):
            return executable
    return None


def launch_in_new_powershell(
    command,
    cleanup_paths=(),
    debug_messages=(),
    mpv_executable=None,
    mpv_arguments=None,
):
    if os.name != "nt":
        return False
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not powershell:
        return False
    script_lines = [
        f"Write-Host {powershell_quote(message)}"
        for message in debug_messages
    ]
    if cleanup_paths:
        script_lines.append(
            'Write-Host "[subtitle-debug] Waiting for mpv process to exit before cleaning temporary subtitles."'
        )
        if mpv_executable and mpv_arguments is not None:
            process_arguments = subprocess.list2cmdline(mpv_arguments)
            script_lines.extend((
                "try {",
                "$mpvStartInfo = New-Object System.Diagnostics.ProcessStartInfo",
                f"$mpvStartInfo.FileName = {powershell_quote(mpv_executable)}",
                f"$mpvStartInfo.Arguments = {powershell_quote(process_arguments)}",
                "$mpvStartInfo.UseShellExecute = $false",
                "$mpvProcess = [System.Diagnostics.Process]::Start($mpvStartInfo)",
                'Write-Host ("[subtitle-debug] mpv process started; PID: " + $mpvProcess.Id)',
                "$mpvProcess.WaitForExit()",
                'Write-Host ("[subtitle-debug] mpv process exited with code: " + $mpvProcess.ExitCode)',
                "} finally {",
            ))
        else:
            script_lines.extend(("try {", command, "} finally {"))
        for path in cleanup_paths:
            quoted_path = powershell_quote(path)
            script_lines.extend((
                f"if (Test-Path -LiteralPath {quoted_path}) {{",
                f"Remove-Item -LiteralPath {quoted_path} -Force -ErrorAction Stop",
                f"Write-Host {powershell_quote(f'[subtitle-debug] Removed temporary subtitle: {path}')}",
                "}",
            ))
        script_lines.append("}")
    else:
        script_lines.append(command)
    subprocess.Popen(
        [powershell, "-NoExit", "-Command", "\n".join(script_lines)],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    return True


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


def make_mpv_command(
    stream_url,
    headers,
    page_url,
    subtitle_urls=(),
    mpv_executable="mpv",
    bitrate=None,
    cache_secs=1300,
    initial_buffer=8,
    subtitles_enabled=True,
):
    mpv_executable, mpv_arguments = make_mpv_arguments(
        stream_url,
        headers,
        page_url,
        subtitle_urls,
        mpv_executable,
        bitrate,
        cache_secs,
        initial_buffer,
        subtitles_enabled,
    )
    executable_command = (
        "mpv"
        if mpv_executable == "mpv"
        else "& " + powershell_quote(mpv_executable)
    )
    return " ".join(
        [executable_command]
        + [powershell_quote(argument) for argument in mpv_arguments]
    )


def make_mpv_arguments(
    stream_url,
    headers,
    page_url,
    subtitle_urls=(),
    mpv_executable="mpv",
    bitrate=None,
    cache_secs=1300,
    initial_buffer=8,
    subtitles_enabled=True,
):
    referer = headers.get("referer", page_url)
    user_agent = headers.get("user-agent", "")
    origin = headers.get("origin", "")
    cookie = headers.get("cookie", "")

    args = []
    if bitrate:
        args.append(f"--hls-bitrate={bitrate}")
    args.append(f"--cache-secs={cache_secs}")
    args.append("--cache-pause-initial=yes")
    args.append(f"--cache-pause-wait={initial_buffer}")
    args.append("--msg-level=all=debug")
    if subtitles_enabled:
        args.extend(("--sid=auto", "--slang=en"))
    else:
        args.append("--sid=no")
    if referer:
        args.append(f"--referrer={referer}")
    if user_agent:
        args.append(f"--user-agent={user_agent}")

    extra_headers = []
    if origin:
        extra_headers.append(f"Origin: {origin}")
    if cookie:
        extra_headers.append(f"Cookie: {cookie}")
    if extra_headers:
        args.append("--http-header-fields=" + ",".join(extra_headers))

    subtitle_urls = tuple(subtitle_urls)
    args.extend("--sub-file=" + url for url in subtitle_urls)
    if urlsplit(stream_url).path.lower().endswith((".m3u8", ".m3u")):
        args.append(stream_url)
    else:
        args.extend((
            "--{",
            "--demuxer-lavf-format=hls",
            stream_url,
            "--}",
        ))
    return mpv_executable, args


def capture_page(page_url, status_callback=None):
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
        browser.close()

    return streams, subtitle_candidates, subtitle_responses, player_video_size


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
    for subtitle_url, is_english in subtitle_candidates:
        if subtitle_url not in hls_subtitles:
            candidate_languages[subtitle_url] = candidate_languages.get(subtitle_url, False) or is_english

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
    )
    command = make_mpv_command(
        stream_url,
        headers,
        page_url,
        standalone_subtitles,
        mpv_executable,
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


class M3u8App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.capture_result = None
        self.stream_url = None
        self.headers = {}
        self.playlist_text = ""
        self.subtitle_responses = {}
        self.quality_options = {}
        self.subtitle_options = {}

        root.title("doki")
        root.geometry("840x742")
        root.minsize(720, 682)
        root.overrideredirect(True)
        root.configure(bg="#d8cdbd")

        style = ttk.Style(root)
        style.theme_use("clam")
        font_directory = resource_path("assets", "jetbrains mono nerd font")
        if os.name == "nt":
            add_font = ctypes.windll.gdi32.AddFontResourceExW
            add_font.argtypes = (ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p)
            add_font.restype = ctypes.c_int
            for font_file in ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf"):
                font_path = os.path.join(font_directory, font_file)
                if os.path.isfile(font_path) and not add_font(font_path, 0x10, None):
                    print(
                        f"[gui] Could not load bundled font {font_file}: {ctypes.WinError()}",
                        file=sys.stderr,
                    )
        available_fonts = set(tkfont.families(root))
        requested_font = next(
            (
                name for name in (
                    "JetBrainsMono Nerd Font",
                    "JetBrainsMono NF",
                    "JetBrains Mono Nerd Font",
                    "JetBrains Mono",
                )
                if name in available_fonts
            ),
            None,
        )
        if requested_font:
            font_family = requested_font
        elif "Cascadia Code" in available_fonts:
            font_family = "Cascadia Code"
            print(
                "[gui] JetBrains Mono Nerd Font is not installed; using Cascadia Code. "
                "Install JetBrains Mono Nerd Font to use it throughout the app.",
                file=sys.stderr,
            )
        elif "Consolas" in available_fonts:
            font_family = "Consolas"
            print(
                "[gui] JetBrains Mono Nerd Font is not installed; using Consolas. "
                "Install JetBrains Mono Nerd Font to use it throughout the app.",
                file=sys.stderr,
            )
        else:
            font_family = "TkDefaultFont"
            print(
                "[gui] JetBrains Mono Nerd Font is not installed; using the system Tk font. "
                "Install JetBrains Mono Nerd Font to use it throughout the app.",
                file=sys.stderr,
            )
        for named_font in (
            "TkDefaultFont",
            "TkTextFont",
            "TkFixedFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
            "TkTooltipFont",
        ):
            tkfont.nametofont(named_font, root=root).configure(family=font_family)
        root.option_add("*Font", (font_family, 10))
        background = "#f5f0e7"
        card = "#fffdf8"
        ink = "#34443c"
        muted = "#78847a"
        green = "#557a68"
        chrome = "#34443c"
        style.configure("App.TFrame", background=background)
        style.configure("Card.TLabelframe", background=card, bordercolor="#e4ddd0", relief="solid", borderwidth=1)
        style.configure(
            "Card.TLabelframe.Label",
            background=card,
            foreground=ink,
            font=(font_family, 11, "bold"),
            padding=(4, 0),
        )
        style.configure("TLabel", background=card, foreground=ink, font=(font_family, 10))
        style.configure("Eyebrow.TLabel", background=background, foreground=green, font=(font_family, 9, "bold"))
        style.configure("Title.TLabel", background=background, foreground=ink, font=(font_family, 25, "bold"))
        style.configure("Subtitle.TLabel", background=background, foreground=muted, font=(font_family, 10))
        style.configure("Muted.TLabel", background=background, foreground=muted, font=(font_family, 9))
        style.configure("TButton", font=(font_family, 10, "bold"), padding=(14, 9), background="#e9e4d9", foreground=ink, borderwidth=0)
        style.map(
            "TButton",
            background=[("pressed", "#d6d0c5"), ("active", "#ded8cc"), ("disabled", "#ebe7df")],
            foreground=[("disabled", "#a6a69e")],
        )
        style.configure("Primary.TButton", font=(font_family, 10, "bold"), padding=(18, 11), background=green, foreground="#ffffff", borderwidth=0)
        style.map(
            "Primary.TButton",
            background=[("disabled", "#b8c5bc"), ("pressed", "#426553"), ("active", "#628774")],
            foreground=[("disabled", "#f5f5f0")],
        )
        style.configure("TEntry", padding=(10, 9), fieldbackground=card, foreground=ink, bordercolor="#ded8cc", lightcolor="#ded8cc", darkcolor="#ded8cc")
        style.map("TEntry", bordercolor=[("focus", green)], lightcolor=[("focus", green)], darkcolor=[("focus", green)])
        style.configure("TCombobox", padding=(9, 7), fieldbackground=card, foreground=ink, background="#eee9df", arrowcolor=green)
        style.map("TCombobox", fieldbackground=[("readonly", card)], foreground=[("readonly", ink)], background=[("active", "#e2ddd2")])
        style.configure("TSpinbox", padding=(8, 6), fieldbackground=card, foreground=ink, arrowcolor=green)
        style.configure("Warm.Horizontal.TProgressbar", troughcolor="#e8e1d5", background=green, bordercolor="#e8e1d5", lightcolor=green, darkcolor=green)

        self.url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.quality_var = tk.StringVar(value="Auto (mpv default)")
        self.subtitle_var = tk.StringVar(value="No subtitles")
        self.cache_var = tk.StringVar(value="1300")
        self.buffer_var = tk.StringVar(value="8")

        shell = tk.Frame(root, bg="#d8cdbd", padx=1, pady=1)
        shell.pack(fill="both", expand=True)
        surface = tk.Frame(shell, bg=background)
        surface.pack(fill="both", expand=True)

        titlebar = tk.Frame(surface, bg=chrome, height=42)
        titlebar.pack(fill="x")
        titlebar.pack_propagate(False)
        titlebar.columnconfigure(0, weight=1)
        titlebar.columnconfigure(1, weight=0)
        titlebar.columnconfigure(2, weight=1)
        title_label = tk.Label(
            titlebar,
            text="DOKI",
            bg=chrome,
            fg="#f5f0e7",
            font=(font_family, 9, "bold"),
            padx=0,
            pady=0,
        )
        title_label.grid(row=0, column=1, sticky="nsew")
        title_label.bind("<ButtonPress-1>", self._start_window_drag)
        title_label.bind("<B1-Motion>", self._drag_window)
        controls = tk.Frame(titlebar, bg=chrome)
        controls.grid(row=0, column=2, sticky="e", padx=(0, 5))
        minimize_button = tk.Label(
            controls,
            text="—",
            bg=chrome,
            fg="#f5f0e7",
            font=(font_family, 12),
            width=4,
            cursor="hand2",
        )
        minimize_button.pack(side="left", padx=(0, 2), ipady=2)
        minimize_button.bind("<Enter>", lambda _event: minimize_button.configure(bg="#52665a"))
        minimize_button.bind("<Leave>", lambda _event: minimize_button.configure(bg=chrome))
        minimize_button.bind("<Button-1>", lambda _event: root.iconify())
        close_button = tk.Label(
            controls,
            text="×",
            bg=chrome,
            fg="#f5f0e7",
            font=(font_family, 15),
            width=4,
            cursor="hand2",
        )
        close_button.pack(side="left", ipady=1)
        close_button.bind("<Enter>", lambda _event: close_button.configure(bg="#b85c54"))
        close_button.bind("<Leave>", lambda _event: close_button.configure(bg=chrome))
        close_button.bind("<Button-1>", lambda _event: root.destroy())
        titlebar.bind("<ButtonPress-1>", self._start_window_drag)
        titlebar.bind("<B1-Motion>", self._drag_window)

        body = ttk.Frame(surface, padding=(38, 30, 38, 28), style="App.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        heading = ttk.Frame(body, style="App.TFrame")
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="A LITTLE COZY PLAYER FOR THE BOYS", style="Eyebrow.TLabel").grid(
            row=0, column=0, sticky="w", pady=(3, 0)
        )
        # ttk.Label(heading, text="doki", style="Title.TLabel").grid(
        #     row=1, column=0, sticky="w", pady=(4, 2)
        # )
        ttk.Label(
            heading,
            text="Settle in, pick your stream, and let mpv take it from here.",
            style="Subtitle.TLabel",
        ).grid(row=2, column=0, sticky="w")
        self.mascot_canvas = tk.Canvas(
            heading,
            width=116,
            height=132,
            bg="#f5f0e7",
            highlightthickness=0,
            borderwidth=0,
        )
        self.mascot_canvas.grid(row=0, column=1, rowspan=3, sticky="e", padx=(12, 0))
        self._mascot_frame = 0
        self._mascot_images = []
        mascot_path = resource_path("assets", "dancing-anime-girl.gif")
        if os.path.isfile(mascot_path):
            try:
                with open(mascot_path, "rb") as mascot_file:
                    image_data = base64.b64encode(mascot_file.read()).decode("ascii")
                frame_index = 0
                while True:
                    try:
                        image = tk.PhotoImage(
                            data=image_data,
                            format=f"gif -index {frame_index}",
                        )
                    except tk.TclError:
                        break
                    scale = max(1, (max(image.width(), image.height()) + 111) // 112)
                    self._mascot_images.append(image.subsample(scale, scale))
                    frame_index += 1
            except tk.TclError as error:
                print(f"[gui] Could not load dancing mascot GIF: {error}", file=sys.stderr)
            if not self._mascot_images:
                print(f"[gui] Dancing mascot GIF contains no readable frames: {mascot_path}", file=sys.stderr)
                self.mascot_canvas.create_text(
                    58, 66, text="Mascot unavailable", fill="#78847a",
                    font=(font_family, 8),
                )
        else:
            print(f"[gui] Dancing mascot GIF not found: {mascot_path}", file=sys.stderr)
            self.mascot_canvas.create_text(
                58, 66, text="Mascot unavailable", fill="#78847a",
                font=(font_family, 8),
            )
        self._animate_mascot()

        episode = ttk.LabelFrame(body, text="  Episode  ", padding=(18, 15), style="Card.TLabelframe")
        episode.grid(row=1, column=0, sticky="ew", pady=(14, 14))
        episode.columnconfigure(0, weight=1)
        ttk.Label(episode, text="Paste the episode or player link").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        self.url_entry = ttk.Entry(episode, textvariable=self.url_var, font=(font_family, 11))
        self.url_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        self.analyze_button = ttk.Button(episode, text="Find stream", command=self.analyze)
        self.analyze_button.grid(row=1, column=1, sticky="ew")
        self.url_entry.bind("<Return>", lambda _event: self.analyze())

        self.progress = ttk.Progressbar(body, mode="indeterminate", length=100, style="Warm.Horizontal.TProgressbar")
        self.progress.grid(row=2, column=0, sticky="ew", pady=(1, 7))
        ttk.Label(body, textvariable=self.status_var, style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 17))

        playback = ttk.LabelFrame(body, text="  Make yourself at home - IN MEMORY OF TIM BERGMAN ", padding=(18, 16), style="Card.TLabelframe")
        playback.grid(row=4, column=0, sticky="ew")
        playback.columnconfigure(0, weight=1)
        playback.columnconfigure(1, weight=1)

        ttk.Label(playback, text="Stream quality").grid(row=0, column=0, sticky="w", padx=(0, 14), pady=(0, 6))
        ttk.Label(playback, text="Subtitles").grid(row=0, column=1, sticky="w", pady=(0, 6))
        self.quality_combo = ttk.Combobox(
            playback, textvariable=self.quality_var, values=("Auto (mpv default)",), state="readonly"
        )
        self.quality_combo.grid(row=1, column=0, sticky="ew", padx=(0, 14), pady=(0, 20))
        self.subtitle_combo = ttk.Combobox(
            playback, textvariable=self.subtitle_var, values=("No subtitles",), state="readonly"
        )
        self.subtitle_combo.grid(row=1, column=1, sticky="ew", pady=(0, 20))

        ttk.Label(playback, text="Cache · seconds").grid(row=2, column=0, sticky="w", padx=(0, 14), pady=(0, 6))
        ttk.Label(playback, text="Initial buffer · seconds").grid(row=2, column=1, sticky="w", pady=(0, 6))
        self.cache_spin = ttk.Spinbox(playback, from_=5, to=180, increment=5, textvariable=self.cache_var, width=10)
        self.cache_spin.grid(row=3, column=0, sticky="w", padx=(0, 14))
        self.buffer_spin = ttk.Spinbox(playback, from_=0, to=45, increment=1, textvariable=self.buffer_var, width=10)
        self.buffer_spin.grid(row=3, column=1, sticky="w")

        footer = ttk.Frame(body, style="App.TFrame")
        footer.grid(row=5, column=0, sticky="ew", pady=(22, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, text="Your video will open in a separate player window.", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.start_button = ttk.Button(footer, text="  Start watching  ", style="Primary.TButton", command=self.start_mpv)
        self.start_button.grid(row=0, column=1, sticky="e")
        self.start_button.state(["disabled"])

        root.after(100, self.poll_events)
        self._taskbar_registered = False
        root.after(100, self._register_custom_taskbar_button)
        self.url_entry.focus_set()

    def _register_custom_taskbar_button(self):
        if os.name != "nt" or self._taskbar_registered:
            return

        self.root.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
        if not hwnd:
            raise ctypes.WinError()

        get_window_long = user32.GetWindowLongPtrW
        get_window_long.argtypes = (ctypes.c_void_p, ctypes.c_int)
        get_window_long.restype = ctypes.c_ssize_t
        set_window_long = user32.SetWindowLongPtrW
        set_window_long.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
        set_window_long.restype = ctypes.c_ssize_t

        ex_style_index = -20
        app_window = 0x00040000
        tool_window = 0x00000080
        extended_style = get_window_long(hwnd, ex_style_index)
        ctypes.set_last_error(0)
        set_window_long(hwnd, ex_style_index, (extended_style | app_window) & ~tool_window)
        if ctypes.get_last_error():
            raise ctypes.WinError()

        set_window_pos = user32.SetWindowPos
        set_window_pos.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        )
        set_window_pos.restype = ctypes.c_int
        if not set_window_pos(hwnd, None, 0, 0, 0, 0, 0x0037):
            raise ctypes.WinError()

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        ole32 = ctypes.windll.ole32
        ole32.CLSIDFromString.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(GUID))
        ole32.CLSIDFromString.restype = ctypes.c_long

        def parse_guid(value):
            parsed = GUID()
            result = ole32.CLSIDFromString(value, ctypes.byref(parsed))
            if result < 0:
                raise OSError(f"Invalid Windows taskbar interface GUID: {value}")
            return parsed

        ole32.CoInitialize.argtypes = (ctypes.c_void_p,)
        ole32.CoInitialize.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = ()
        ole32.CoUninitialize.restype = None
        init_result = ole32.CoInitialize(None)
        changed_mode = ctypes.c_uint32(init_result).value == 0x80010106
        if init_result < 0 and not changed_mode:
            raise OSError(
                f"COM initialization failed: 0x{ctypes.c_uint32(init_result).value:08X}"
            )

        taskbar_list = ctypes.c_void_p()
        try:
            taskbar_class = parse_guid("{56FDF344-FD6D-11D0-958A-006097C9A090}")
            taskbar_interface = parse_guid("{56FDF342-FD6D-11D0-958A-006097C9A090}")
            ole32.CoCreateInstance.argtypes = (
                ctypes.POINTER(GUID),
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(GUID),
                ctypes.POINTER(ctypes.c_void_p),
            )
            ole32.CoCreateInstance.restype = ctypes.c_long
            result = ole32.CoCreateInstance(
                ctypes.byref(taskbar_class),
                None,
                1,
                ctypes.byref(taskbar_interface),
                ctypes.byref(taskbar_list),
            )
            if result < 0:
                raise OSError(
                    f"Could not create Windows taskbar interface: "
                    f"0x{ctypes.c_uint32(result).value:08X}"
                )

            vtable = ctypes.cast(
                taskbar_list,
                ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
            ).contents
            initialize = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[3])
            add_tab = ctypes.WINFUNCTYPE(
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_void_p,
            )(vtable[4])
            result = initialize(taskbar_list)
            if result < 0:
                raise OSError(
                    f"Could not initialize Windows taskbar interface: "
                    f"0x{ctypes.c_uint32(result).value:08X}"
                )
            result = add_tab(taskbar_list, ctypes.c_void_p(hwnd))
            if result < 0:
                raise OSError(
                    f"Could not register the app with the taskbar: "
                    f"0x{ctypes.c_uint32(result).value:08X}"
                )
            self._taskbar_registered = True
            print("[gui] Registered the custom-title-bar window with the Windows taskbar.")
        finally:
            if taskbar_list.value:
                vtable = ctypes.cast(
                    taskbar_list,
                    ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
                ).contents
                release = ctypes.WINFUNCTYPE(
                    ctypes.c_ulong,
                    ctypes.c_void_p,
                )(vtable[2])
                release(taskbar_list)
            if not changed_mode and init_result >= 0:
                ole32.CoUninitialize()

    def _start_window_drag(self, event):
        self._window_drag_offset_x = event.x_root - self.root.winfo_x()
        self._window_drag_offset_y = event.y_root - self.root.winfo_y()

    def _drag_window(self, event):
        x = event.x_root - self._window_drag_offset_x
        y = event.y_root - self._window_drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def _animate_mascot(self):
        if self._mascot_images:
            image = self._mascot_images[self._mascot_frame % len(self._mascot_images)]
            self.mascot_canvas.delete("all")
            self.mascot_canvas.create_image(58, 66, image=image)
            self._mascot_frame += 1
        self.root.after(80, self._animate_mascot)

    def analyze(self):
        page_url = self.url_var.get().strip()
        parsed = urlsplit(page_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            messagebox.showerror("Invalid URL", "Enter a complete http or https episode URL.", parent=self.root)
            return

        self.capture_result = None
        self.start_button.state(["disabled"])
        self.analyze_button.state(["disabled"])
        self.status_var.set("Opening the page in a browser...")
        self.progress.start(12)
        threading.Thread(target=self.capture_worker, args=(page_url,), daemon=True).start()

    def capture_worker(self, page_url):
        try:
            result = capture_page(page_url, lambda text: self.events.put(("status", text)))
        except Exception as error:
            self.events.put(("error", str(error)))
        else:
            self.events.put(("result", result))

    def poll_events(self):
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "status":
                self.status_var.set(payload)
            elif event == "error":
                self.progress.stop()
                self.analyze_button.state(["!disabled"])
                self.status_var.set("Capture failed")
                messagebox.showerror("Browser capture failed", payload, parent=self.root)
            else:
                self.finish_capture(payload)
        self.root.after(100, self.poll_events)

    def finish_capture(self, result):
        self.progress.stop()
        self.analyze_button.state(["!disabled"])
        streams, subtitle_candidates, subtitle_responses, player_video_size = result
        if not streams:
            self.status_var.set("No HLS stream found. Try again and press Play in the browser if needed.")
            return

        self.capture_result = result
        self.stream_url, self.headers, self.playlist_text, response_status, content_type = max(
            streams,
            key=lambda item: ("#EXT-X-STREAM-INF:" in item[2], len(item[2])),
        )
        _, hls_subtitles = parse_hls_playlist(self.stream_url, self.playlist_text)

        self.quality_options = dict(make_quality_options(self.stream_url, self.playlist_text))
        quality_labels = list(self.quality_options)
        self.quality_combo.configure(values=quality_labels)
        self.quality_var.set(quality_labels[0])

        subtitle_choices = make_subtitle_options(subtitle_candidates, hls_subtitles)
        self.subtitle_options = {label: selection for label, selection in subtitle_choices}
        subtitle_labels = list(self.subtitle_options)
        self.subtitle_combo.configure(values=subtitle_labels)
        preferred_subtitle = next(
            (label for label, selection in subtitle_choices if selection["kind"] == "playlist"),
            None,
        )
        if preferred_subtitle is None:
            preferred_subtitle = next(
                (label for label, selection in subtitle_choices if selection.get("english")),
                subtitle_labels[0],
            )
        self.subtitle_var.set(preferred_subtitle)

        variant_count = len(parse_hls_variants(self.stream_url, self.playlist_text))
        detail = f"HTTP {response_status} {content_type or ''}".strip()
        if variant_count:
            detail += f" - {variant_count} quality options"
        if player_video_size and player_video_size[0] and player_video_size[1]:
            detail += f" - detected {player_video_size[0]}x{player_video_size[1]}"
        self.status_var.set(f"Stream ready: {detail}")
        self.start_button.state(["!disabled"])

    def start_mpv(self):
        if not self.capture_result or not self.stream_url:
            return
        mpv_executable = find_mpv_executable()
        if not mpv_executable:
            messagebox.showerror(
                "mpv is required",
                "Install mpv, then add mpv.exe to PATH or register it with Windows before starting playback.",
                parent=self.root,
            )
            return
        try:
            cache_secs = int(self.cache_var.get())
            initial_buffer = int(self.buffer_var.get())
            if not 5 <= cache_secs <= 1320 or not 0 <= initial_buffer <= 45:
                raise ValueError("Cache must be 5-1320 seconds and initial buffer 0-45 seconds.")
        except ValueError as error:
            messagebox.showerror("Invalid buffering options", str(error), parent=self.root)
            return

        selection = self.subtitle_options[self.subtitle_var.get()]
        subtitle_urls = ()
        cleanup_paths = []
        subtitles_enabled = selection["kind"] != "none"
        if selection["kind"] == "external":
            subtitle_url = selection["url"]
            _, _, subtitle_responses, _ = self.capture_result
            local_file = save_captured_subtitle(subtitle_url, subtitle_responses.get(subtitle_url))
            subtitle_urls = (local_file or subtitle_url,)
            if local_file:
                cleanup_paths.append(local_file)

        command = make_mpv_command(
            self.stream_url,
            self.headers,
            self.url_var.get().strip(),
            subtitle_urls,
            mpv_executable,
            bitrate=self.quality_options[self.quality_var.get()],
            cache_secs=cache_secs,
            initial_buffer=initial_buffer,
            subtitles_enabled=subtitles_enabled,
        )
        launch_executable, launch_arguments = make_mpv_arguments(
            self.stream_url,
            self.headers,
            self.url_var.get().strip(),
            subtitle_urls,
            mpv_executable,
            bitrate=self.quality_options[self.quality_var.get()],
            cache_secs=cache_secs,
            initial_buffer=initial_buffer,
            subtitles_enabled=subtitles_enabled,
        )
        _, subtitle_candidates, _, _ = self.capture_result
        _, hls_subtitles = parse_hls_playlist(self.stream_url, self.playlist_text)
        debug_messages = [
            f"[subtitle-debug] selected source: {selection['kind']}",
            f"[subtitle-debug] HLS English tracks detected: {len(hls_subtitles)}",
            f"[subtitle-debug] external subtitle candidates detected: {len(subtitle_candidates)}",
            f"[subtitle-debug] subtitles enabled: {'yes' if subtitles_enabled else 'no'}",
        ]
        if selection["kind"] == "external":
            debug_messages.append(
                "[subtitle-debug] external subtitle supplied from "
                + ("a captured local file" if cleanup_paths else "its original URL")
            )
        try:
            if not launch_in_new_powershell(
                command,
                cleanup_paths,
                debug_messages,
                launch_executable,
                launch_arguments,
            ):
                raise OSError("Could not open PowerShell. Check that PowerShell is installed.")
        except OSError as error:
            messagebox.showerror("Could not start mpv", str(error), parent=self.root)
            return
        self.status_var.set("Started mpv in a new PowerShell window.")


def main():
    root = tk.Tk()
    M3u8App(root)
    root.mainloop()


if __name__ == "__main__":
    if "--cli" in sys.argv[1:]:
        console_main()
    else:
        main()