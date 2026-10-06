# doki

doki was created to make watching anime with [Anime4K](https://github.com/bloc97/anime4k) on MPV easier and more convenient. It also lets you watch episodes without dealing with the ads, popups, and other distractions commonly found on streaming sites.

## Download and run

Download `doki-Windows-x64.zip` from the latest GitHub release, extract the whole folder, and double-click **doki.exe**. Everything is bundled: Chromium, mpv, the Anime4K shaders and JetBrains Mono Nerd Font. You don't need to install anything or edit an `mpv.conf`.

Paste an episode or player URL and choose **Find stream**. You don't need to play the stream, as the app *should* find the M3U8 and English subs (if available) anyways!

- **Anime4K upscaling:** pick a preset in the app (Mode A for most 1080p anime, B for 720p or softer sources, C for 480p or noisy sources; use *Fast* on weaker GPUs). In the player, `Ctrl+1`-`Ctrl+6` switch modes and `Ctrl+0` turns the shaders off. Choose *Use my mpv config* to leave shaders to your own mpv setup.
- **Recently watched** and **Next episode** sit under the link box.
- **Resume:** doki remembers where you stopped and offers to continue next time.
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

The code lives in the `doki` package: `capture` (Chromium stream capture), `hls`, `subtitles`, `mpv` (finding/launching mpv), `anime4k` (shader presets), `library` (history, next episode, resume), `gui` and `cli`.

The bundled JetBrains Mono Nerd Font is distributed under the SIL Open Font License; see `assets/jetbrains mono nerd font/LICENSE.txt`. mpv is GPLv2+ and Anime4K is MIT licensed; see `mpv/LICENSE-NOTICE.txt` in the release.
