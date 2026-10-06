"""Locating and launching mpv."""

import os
import shutil
import subprocess
import threading
from urllib.parse import urlsplit

from .paths import IS_MAC, app_path


def powershell_quote(value):
    escaped = value.replace("`", "``").replace('"', '`"').replace("$", "`$")
    return '"' + escaped + '"'


# Where GUI apps on macOS can find mpv, since they don't inherit the shell's PATH.
MAC_MPV_LOCATIONS = (
    "/opt/homebrew/bin/mpv",
    "/usr/local/bin/mpv",
    "/Applications/mpv.app/Contents/MacOS/mpv",
)


def bundled_mpv_executable():
    if IS_MAC:
        executable = app_path("mpv", "mpv.app", "Contents", "MacOS", "mpv")
    else:
        executable = app_path("mpv", "mpv.exe")
    return executable if os.path.isfile(executable) else None


def bundled_config_arguments(mpv_executable):
    """mpv only reads portable_config by itself on Windows, so point the macOS build at it."""
    if IS_MAC and mpv_executable == bundled_mpv_executable():
        return [f"--config-dir={app_path('mpv', 'portable_config')}"]
    return []


def find_mpv_executable():
    bundled = bundled_mpv_executable()
    if bundled:
        return bundled
    for name in ("mpv.exe", "mpv"):
        executable = shutil.which(name)
        if executable:
            return executable
    if IS_MAC:
        return next((path for path in MAC_MPV_LOCATIONS if os.path.isfile(path)), None)
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


def launch_mpv(mpv_executable, mpv_arguments, cleanup_paths=()):
    """Starts mpv without a console and removes temporary files once it exits."""
    process = subprocess.Popen(
        [mpv_executable, *mpv_arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if cleanup_paths:
        def cleanup():
            process.wait()
            for path in cleanup_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass

        threading.Thread(target=cleanup, daemon=True).start()
    return process


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
    extra_args=(),
    debug=False,
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
        extra_args,
        debug,
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
    extra_args=(),
    debug=False,
):
    referer = headers.get("referer", page_url)
    user_agent = headers.get("user-agent", "")
    origin = headers.get("origin", "")
    cookie = headers.get("cookie", "")

    args = bundled_config_arguments(mpv_executable)
    if bitrate:
        args.append(f"--hls-bitrate={bitrate}")
    args.append(f"--cache-secs={cache_secs}")
    args.append("--cache-pause-initial=yes")
    args.append(f"--cache-pause-wait={initial_buffer}")
    if debug:
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
    args.extend(extra_args)

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
