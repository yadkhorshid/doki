# doki

doki was created to make watching anime with [Anime4K](https://github.com/bloc97/anime4k) on MPV easier and more convenient. It also lets you watch episodes without dealing with the ads, popups, and other distractions commonly found on streaming sites.

## Download and run

Download `doki-Windows-x64.zip` from the latest GitHub release, extract the whole folder, and double-click **doki.exe**. Chromium and JetBrains Mono Nerd Font are bundled; no Python setup is needed.

**mpv must be installed separately.** Make sure `mpv.exe` is on `PATH` or registered with Windows before starting playback.

Paste an episode or player URL and choose **Find stream**. You don't need to play the stream, as the app *should* find the M3U8 anyways!

## Build on Windows

With Python 3.13 and PowerShell installed, run:

```powershell
.\build.ps1
```

The script installs build requirements, downloads Chromium, and creates the portable folder and ZIP under `dist`. The package is large because it includes Chromium.

The bundled JetBrains Mono Nerd Font is distributed under the SIL Open Font License; see `assets/jetbrains mono nerd font/LICENSE.txt`.
