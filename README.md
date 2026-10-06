# doki

doki was created to make watching anime with [Anime4K](https://github.com/bloc97/anime4k) on MPV easier and more convenient. It also lets you watch episodes without dealing with the ads, popups, and other distractions commonly found on streaming sites.

## Download and run

Download the ZIP for your computer from the latest GitHub release. Everything is bundled: Chromium, mpv, the Anime4K shaders and JetBrains Mono Nerd Font. You don't need to install anything or edit an `mpv.conf`.

- **Windows:** `doki-Windows-x64.zip`. Extract the whole folder and double-click **doki.exe**.
- **Mac with Apple Silicon (M1 or newer):** `doki-macOS-arm64.zip`. Needs macOS 14 Sonoma or newer.
- **Mac with an Intel chip:** `doki-macOS-intel.zip`. Needs macOS 15 Sequoia or newer.

On a Mac, unzip it and move **doki.app** to Applications. doki isn't signed with an Apple developer certificate, so macOS blocks it the first time. To open it anyway, run this once in Terminal:

```sh
xattr -dr com.apple.quarantine /Applications/doki.app
```

You can also right-click doki.app, choose **Open**, then **Open** again. If macOS still refuses, go to **System Settings → Privacy & Security** and choose **Open Anyway**.

Paste an episode or player URL and choose **Find stream**. doki looks for the M3U8 and any subtitles in a hidden browser with ads and popups blocked. If it can't find them, it opens the browser so you can press Play.

- **Anime4K upscaling:** *Auto* picks the mode from the stream's resolution (Mode A+A for 1080p, B for 720p, C for 480p and below). You can also pick a preset yourself.
  - A+A is the highest-quality mode for 1080p, but it's also the heaviest. On a weaker GPU (e.g. laptop integrated graphics) it can stutter or drop frames. If it does, pick *Mode A (HQ)* or one of the *Fast* presets, or press `Ctrl+1` in the player to switch to Mode A.
  - In the player, `Ctrl+1`-`Ctrl+6` switch modes and `Ctrl+0` turns the shaders off. Choose *Use my mpv config* to leave shaders to your own mpv setup.
- **Subtitles in any language:** the Subtitles list shows every track doki finds, by language (e.g. *Spanish (from playlist)*). doki remembers the language you pick and selects it again next time. It falls back to English, or to no subtitles if neither is available.
- **Recently watched** and **Next episode** sit under the link box.
- **Resume:** doki remembers where you stopped and offers to continue next time.
- mpv opens on its own, without a console. If something goes wrong, tick **Show debug console when playing** to see mpv's debug log. On a Mac the option is **Save an mpv debug log when playing**, and doki shows where the log was saved.
- Settings, history and resume positions are stored in `%APPDATA%\doki` on Windows and `~/Library/Application Support/doki` on a Mac.

doki uses its bundled mpv. If that's missing, it falls back to an mpv on `PATH` or registered with Windows, or on a Mac to one installed with Homebrew or in Applications.

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

## Build on macOS

With Python 3.13 (from python.org, which includes Tk) run:

```sh
./build-macos.sh
```

It builds for the Mac's own chip, bundles the official mpv macOS build and the Anime4K shaders, and creates `dist/doki.app` and `dist/doki-macOS-arm64.zip` (or `-intel.zip`). Pass `--refresh-mpv` to download mpv again.

## Releases

Pushing a `v*` tag runs [.github/workflows/release.yml](.github/workflows/release.yml). It builds Windows and both Mac versions on GitHub's runners, runs `tests/smoke_test.py` and checks that each packaged app starts. It then publishes the release with the notes from `release-notes/<tag>.md`. Pushing to a `ci/*` branch runs the same builds and tests without publishing.

The code lives in the `doki` package: `capture` (Chromium stream capture), `adblock`, `hls`, `subtitles`, `mpv` (finding/launching mpv), `anime4k` (shader presets), `library` (history, next episode, resume), `gui` and `cli`.

The bundled JetBrains Mono Nerd Font is distributed under the SIL Open Font License; see `assets/jetbrains mono nerd font/LICENSE.txt`. mpv is GPLv2+ and Anime4K is MIT licensed; see `mpv/LICENSE-NOTICE.txt` in the release.
