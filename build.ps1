param(
    # Re-download mpv and the Anime4K shaders even if mpv\ already has them.
    [switch]$RefreshMpv
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ProjectRoot = $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source
$DistRoot = Join-Path $ProjectRoot "dist"
$AppDirectory = Join-Path $DistRoot "doki"
$Archive = Join-Path $DistRoot "doki-Windows-x64.zip"
$MpvDirectory = Join-Path $ProjectRoot "mpv"
$MpvConfigDirectory = Join-Path $MpvDirectory "portable_config"
$ShaderDirectory = Join-Path $MpvConfigDirectory "shaders"
$DownloadDirectory = Join-Path $ProjectRoot "build\downloads"
$Anime4KUrl = "https://github.com/bloc97/Anime4K/releases/download/v4.0.1/Anime4K_v4.0.zip"

Push-Location $ProjectRoot
try {
    & $Python -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install build requirements."
    }

    & $Python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the Playwright Chromium browser."
    }

    if ($RefreshMpv -and (Test-Path -LiteralPath $MpvDirectory)) {
        Remove-Item -LiteralPath $MpvDirectory -Recurse -Force
    }
    New-Item -ItemType Directory -Path $DownloadDirectory, $ShaderDirectory -Force | Out-Null

    if (-not (Test-Path -LiteralPath (Join-Path $MpvDirectory "mpv.exe"))) {
        $Release = Invoke-RestMethod "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
        $Asset = $Release.assets | Where-Object { $_.name -match "^mpv-x86_64-\d{8}-git-[0-9a-f]+\.7z$" } | Select-Object -First 1
        if (-not $Asset) {
            throw "Could not find an x86_64 mpv build in the latest shinchiro/mpv-winbuild-cmake release."
        }
        $MpvArchive = Join-Path $DownloadDirectory $Asset.name
        Write-Host "Downloading $($Asset.name)"
        Invoke-WebRequest $Asset.browser_download_url -OutFile $MpvArchive
        New-Item -ItemType Directory -Path $MpvDirectory -Force | Out-Null
        # Windows 10 1803+ tar (libarchive) handles the BCJ2 filter that mpv's 7z uses.
        & tar.exe -xf $MpvArchive -C $MpvDirectory
        if ($LASTEXITCODE -ne 0) {
            throw "Could not extract $MpvArchive. Extract it into $MpvDirectory with 7-Zip and run the build again."
        }
        Set-Content -LiteralPath (Join-Path $MpvDirectory "LICENSE-NOTICE.txt") -Encoding utf8 -Value @(
            "This folder contains mpv ($($Asset.name)), built by shinchiro/mpv-winbuild-cmake,",
            "and the Anime4K v4.0 shaders (MIT License, https://github.com/bloc97/Anime4K).",
            "mpv is free software licensed under the GPLv2 or later; see https://github.com/mpv-player/mpv",
            "for its license and source code, and https://github.com/shinchiro/mpv-winbuild-cmake for the build scripts."
        )
    }

    if (-not (Test-Path -LiteralPath (Join-Path $ShaderDirectory "Anime4K_Clamp_Highlights.glsl"))) {
        $ShaderArchive = Join-Path $DownloadDirectory "Anime4K_v4.0.zip"
        Write-Host "Downloading Anime4K shaders"
        Invoke-WebRequest $Anime4KUrl -OutFile $ShaderArchive
        Expand-Archive -LiteralPath $ShaderArchive -DestinationPath $ShaderDirectory -Force
    }
    Copy-Item -Path (Join-Path $ProjectRoot "assets\mpv-config\*") -Destination $MpvConfigDirectory -Force

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name "doki" `
        --add-data "assets;assets" `
        --collect-all playwright `
        --collect-all greenlet `
        --collect-all pyee `
        main.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }

    $BrowserExecutable = & $Python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $BrowserExecutable)) {
        throw "Could not locate the Playwright Chromium executable."
    }
    $ChromiumDirectory = Split-Path (Split-Path $BrowserExecutable -Parent) -Parent
    $ChromiumRevision = Split-Path $ChromiumDirectory -Leaf
    $BrowserInstallRoot = Split-Path $ChromiumDirectory -Parent
    $HeadlessShellDirectory = Join-Path $BrowserInstallRoot ($ChromiumRevision -replace "^chromium-", "chromium_headless_shell-")
    if (-not (Test-Path -LiteralPath $HeadlessShellDirectory)) {
        throw "Could not locate the matching Playwright Chromium headless shell."
    }
    $BundledBrowserDirectory = Join-Path $AppDirectory "browsers"
    New-Item -ItemType Directory -Path $BundledBrowserDirectory -Force | Out-Null
    Copy-Item -LiteralPath $ChromiumDirectory -Destination $BundledBrowserDirectory -Recurse -Force
    Copy-Item -LiteralPath $HeadlessShellDirectory -Destination $BundledBrowserDirectory -Recurse -Force

    Copy-Item -LiteralPath $MpvDirectory -Destination $AppDirectory -Recurse -Force

    if (Test-Path -LiteralPath $Archive) {
        Remove-Item -LiteralPath $Archive -Force
    }
    Compress-Archive -LiteralPath $AppDirectory -DestinationPath $Archive -CompressionLevel Optimal

    Write-Host "Portable app folder: $AppDirectory"
    Write-Host "Portable download:   $Archive"
    Write-Host "Bundled mpv and Anime4K shaders from: $MpvDirectory"
}
finally {
    Pop-Location
}
