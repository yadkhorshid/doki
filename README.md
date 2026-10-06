# doki

doki was created to make watching anime with [Anime4K](https://github.com/bloc97/anime4k) on MPV easier and more convenient. It also lets you watch episodes without dealing with the ads, popups, and other distractions commonly found on streaming sites.

## Download and run

Download `doki-Windows-x64.zip` from the latest GitHub release, extract the whole folder, and double-click **doki.exe**. Everything is bundled: Chromium, mpv, the Anime4K shaders and JetBrains Mono Nerd Font. You don't need to install anything or edit an `mpv.conf`.

Paste an episode or player URL and choose **Find stream**. doki looks for the M3U8 and English subs (if available) in a hidden browser with ads and popups blocked. If it can't find them, it opens the browser so you can press Play.

- **Anime4K upscaling:** *Auto* picks the mode from the stream's resolution (Mode A+A for 1080p, B for 720p, C for 480p and below). You can also pick a preset yourself.
  - A+A is the highest-quality mode for 1080p, but it's also the heaviest. On a weaker GPU (e.g. laptop integrated graphics) it can stutter or drop frames. If it does, pick *Mode A (HQ)* or one of the *Fast* presets, or press `Ctrl+1` in the player to switch to Mode A.
  - In the player, `Ctrl+1`-`Ctrl+6` switch modes and `Ctrl+0` turns the shaders off. Choose *Use my mpv config* to leave shaders to your own mpv setup.
- **Recently watched** and **Next episode** sit under the link box.
- **Resume:** doki remembers where you stopped and offers to continue next time.
- mpv opens on its own, without a console. Tick **Show debug console when playing** to see mpv's debug log when something goes wrong.
- Settings, history and resume positions are stored in `%APPDATA%\doki`.

doki uses its bundled mpv and falls back to an mpv on `PATH` (or registered with Windows) if the bundled one is missing.

## Build on Windows

With Python 3.13 and PowerShell installed, run:

```powershell
.\build.ps1
```

The script installs build requirements, downloads Chromium, the latest mpv build from [shinchiro/mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake) and the [Anime4K](https://github.com/bloc97/anime4k) v4.0 shaders, then creates the portable folder and ZIP under `dist`. The package is large because it includes Chromium and mpv.

mpv and the shaders are downloaded once into `mpv\` (git-ignored) and reused; pass `-RefreshMpv` to fetch them again. Running from source uses the same folder:

```powershell
python -m doki          # GUI
python -m doki --cli    # console mode
```

The code lives in the `doki` package: `capture` (Chromium stream capture), `adblock`, `hls`, `subtitles`, `mpv` (finding/launching mpv), `anime4k` (shader presets), `library` (history, next episode, resume), `gui` and `cli`.

The bundled JetBrains Mono Nerd Font is distributed under the SIL Open Font License; see `assets/jetbrains mono nerd font/LICENSE.txt`. mpv is GPLv2+ and Anime4K is MIT licensed; see `mpv/LICENSE-NOTICE.txt` in the release.
