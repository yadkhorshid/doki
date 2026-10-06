$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source
$DistRoot = Join-Path $ProjectRoot "dist"
$AppDirectory = Join-Path $DistRoot "doki"
$Archive = Join-Path $DistRoot "doki-Windows-x64.zip"

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

    if (Test-Path -LiteralPath $Archive) {
        Remove-Item -LiteralPath $Archive -Force
    }
    Compress-Archive -LiteralPath $AppDirectory -DestinationPath $Archive -CompressionLevel Optimal

    Write-Host "Portable app folder: $AppDirectory"
    Write-Host "Portable download:   $Archive"
    Write-Host "mpv is not included; users need to install it separately."
}
finally {
    Pop-Location
}
