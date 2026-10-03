# doki

A cozy Windows app that finds an HLS stream on an episode page and opens it in mpv, with quality and subtitle selection.

## Download and run

Download `doki-Windows-x64.zip` from the latest GitHub release, extract the whole folder, and double-click **doki.exe**. Chromium and JetBrains Mono Nerd Font are bundled; no Python setup is needed.

**mpv must be installed separately.** Make sure `mpv.exe` is on `PATH` or registered with Windows before starting playback.

Paste an episode or player URL and choose **Find stream**. If needed, press Play in the browser window while the app looks for the stream.

## Build on Windows

With Python 3.13 and PowerShell installed, run:

```powershell
.\build.ps1
```

The script installs build requirements, downloads Chromium, and creates the portable folder and ZIP under `dist`. The package is large because it includes Chromium.

The bundled JetBrains Mono Nerd Font is distributed under the SIL Open Font License; see `assets/jetbrains mono nerd font/LICENSE.txt`.
