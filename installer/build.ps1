<#
  Builds the Media Catcher installer on Windows.

  What it does:
    1. downloads the *embeddable* Python and installs the app's packages into it
    2. downloads ffmpeg and deno into a "bin" folder
    3. copies server.py, sitefilter.py, app.py and the browser extension
    4. runs a smoke test, then compiles installer\setup.iss with Inno Setup (if installed)

  Requirements: Windows 10/11, PowerShell 5+, internet. Inno Setup 6.3+ for the final .exe.
  Usage:        installer\build.bat      (or:  powershell -File installer\build.ps1)
#>
param(
    [string]$PythonVersion = "3.12.8",
    [string]$InnoPath = "",    # full path to ISCC.exe, if Inno Setup is installed somewhere unusual
    [switch]$Refresh           # rebuild the Python runtime and re-download deno (gets the newest yt-dlp)
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root  = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Build = Join-Path $Root "build"
$App   = Join-Path $Build "app"
$Cache = Join-Path $Build "cache"
$Dist  = Join-Path $Root "dist"

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Test-Zip($path) {
    try { $z = [System.IO.Compression.ZipFile]::OpenRead($path); $z.Dispose(); return $true }
    catch { return $false }
}

# Downloads to a .part file first and (for zips) verifies it, so an interrupted or
# blocked download can never be left in the cache as a broken file.
function Download($url, $out, [switch]$Zip) {
    if (Test-Path $out) {
        if (-not $Zip -or (Test-Zip $out)) { Write-Host "   (cached) $(Split-Path $out -Leaf)"; return }
        Write-Host "   cached file is corrupt - downloading again" -ForegroundColor Yellow
        Remove-Item -Force $out
    }
    Write-Host "   downloading $url"
    $tmp = "$out.part"
    if (Test-Path $tmp) { Remove-Item -Force $tmp }
    Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -UserAgent "Mozilla/5.0"
    if ($Zip -and -not (Test-Zip $tmp)) {
        $size = (Get-Item $tmp).Length
        Remove-Item -Force $tmp
        throw "The downloaded file is not a valid zip ($size bytes) from $url - check your internet connection, proxy or antivirus, then run the build again."
    }
    Move-Item -Force $tmp $out
}

function Run($exe, $arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $exe $arguments" }
}

# Looks for Inno Setup's command-line compiler (ISCC.exe) in all the usual places.
function Find-Iscc {
    if ($InnoPath -and (Test-Path $InnoPath)) { return $InnoPath }
    if ($env:ISCC -and (Test-Path $env:ISCC)) { return $env:ISCC }
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $roots = @(${env:ProgramFiles(x86)}, $env:ProgramFiles, "$env:LOCALAPPDATA\Programs") | Where-Object { $_ }
    foreach ($r in $roots) {
        $dirs = Get-ChildItem -Path $r -Filter "Inno Setup*" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
        foreach ($d in $dirs) {
            $p = Join-Path $d.FullName "ISCC.exe"
            if (Test-Path $p) { return $p }
        }
    }

    $keys = @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
              "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
              "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*")
    foreach ($k in $keys) {
        $e = Get-ItemProperty $k -ErrorAction SilentlyContinue |
             Where-Object { $_.DisplayName -like "Inno Setup*" -and $_.InstallLocation } | Select-Object -First 1
        if ($e) {
            $p = Join-Path $e.InstallLocation "ISCC.exe"
            if (Test-Path $p) { return $p }
        }
    }
    return $null
}

New-Item -ItemType Directory -Force -Path $Cache, $Dist | Out-Null
Write-Host "Media Catcher build script - revision 0.4.2 (runtime cache, Inno auto-detect, old installers moved to dist\old)" -ForegroundColor Green
if (Test-Path $App) { Remove-Item -Recurse -Force $App }
New-Item -ItemType Directory -Force -Path $App | Out-Null

# ---------------------------------------------------------------- 1. Python runtime (cached)
# The finished runtime (Python + all packages) is saved as a zip in build\cache and reused on the
# next builds, so nothing is downloaded again. It is rebuilt automatically when requirements.txt
# changes, or when you run:  installer\build.bat -Refresh
$PyDir      = Join-Path $App "python"
$Py         = Join-Path $PyDir "python.exe"
$ReqFile    = Join-Path $Root "local_app\requirements.txt"
$ReqHash    = (Get-FileHash $ReqFile -Algorithm SHA256).Hash.Substring(0, 12)
$RuntimeZip = Join-Path $Cache "python-runtime-$PythonVersion-$ReqHash.zip"

if ($Refresh) {
    Get-ChildItem $Cache -Filter "python-runtime-*.zip" -ErrorAction SilentlyContinue | Remove-Item -Force
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Cache "bin\deno.exe"), (Join-Path $Cache "deno-x86_64-pc-windows-msvc.zip")
}

if ((Test-Path $RuntimeZip) -and (Test-Zip $RuntimeZip)) {
    Step "Python runtime (from cache, no downloads - use -Refresh to rebuild with the newest yt-dlp)"
    [System.IO.Compression.ZipFile]::ExtractToDirectory($RuntimeZip, $PyDir)
} else {
    Step "Embeddable Python $PythonVersion"
    $pyZip = Join-Path $Cache "python-$PythonVersion-embed-amd64.zip"
    Download "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" $pyZip -Zip
    Expand-Archive -Path $pyZip -DestinationPath $PyDir -Force

    # Enable site-packages (and the app folder, so "import server" works).
    # Paths in a ._pth file are relative to the file itself: ".." = the app folder.
    $ver = $PythonVersion.Split(".")
    $pth = Get-ChildItem $PyDir -Filter "python*._pth" | Select-Object -First 1
    if (-not $pth) { throw "python*._pth not found in $PyDir" }
    Set-Content -Path $pth.FullName -Encoding ASCII -Value @(
        "python$($ver[0])$($ver[1]).zip", ".", "..", "Lib\site-packages", "import site"
    )

    Step "pip + packages (requirements.txt)"
    $getPip = Join-Path $Cache "get-pip.py"
    Download "https://bootstrap.pypa.io/get-pip.py" $getPip
    Run $Py @($getPip, "--no-warn-script-location", "--no-cache-dir")
    Run $Py @("-m", "pip", "install", "-r", $ReqFile,
              "--no-warn-script-location", "--no-cache-dir", "--only-binary=:all:")

    Step "Saving the Python runtime to the cache"
    Get-ChildItem $Cache -Filter "python-runtime-*.zip*" -ErrorAction SilentlyContinue | Remove-Item -Force
    $tmpZip = "$RuntimeZip.part"
    [System.IO.Compression.ZipFile]::CreateFromDirectory($PyDir, $tmpZip, [System.IO.Compression.CompressionLevel]::Fastest, $false)
    Move-Item -Force $tmpZip $RuntimeZip
}

# ---------------------------------------------------------------- 2. ffmpeg + deno (cached)
$Bin      = Join-Path $App "bin"
$BinCache = Join-Path $Cache "bin"
New-Item -ItemType Directory -Force -Path $Bin, $BinCache | Out-Null

function Get-Tool($name, $zipUrl, $zipName) {
    $cached = Join-Path $BinCache "$name.exe"
    if (Test-Path $cached) {
        Write-Host "   (cached) $name.exe"
    } else {
        $zip = Join-Path $Cache $zipName
        Download $zipUrl $zip -Zip
        $tmp = Join-Path $Cache "$name-extract"
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        $exe = Get-ChildItem $tmp -Recurse -Filter "$name.exe" | Select-Object -First 1
        if (-not $exe) { throw "$name.exe not found in the downloaded archive" }
        Copy-Item $exe.FullName $cached
        Remove-Item -Recurse -Force $tmp
    }
    Copy-Item $cached $Bin
}

Step "ffmpeg"
Get-Tool "ffmpeg" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" "ffmpeg-release-essentials.zip"

Step "deno (JavaScript runtime that yt-dlp needs for YouTube)"
Get-Tool "deno" "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" "deno-x86_64-pc-windows-msvc.zip"

# ---------------------------------------------------------------- 3. app files
Step "App files"
Copy-Item (Join-Path $Root "local_app\server.py") $App
Copy-Item (Join-Path $Root "local_app\app.py") $App
Copy-Item (Join-Path $Root "local_app\sitefilter.py") $App
Copy-Item (Join-Path $PSScriptRoot "debug.bat") $App
Copy-Item (Join-Path $PSScriptRoot "stop.bat") $App
Copy-Item (Join-Path $Root "extension") (Join-Path $App "extension") -Recurse

# ---------------------------------------------------------------- 4. smoke test
Step "Smoke test"
Run $Py @("-c", "import fastapi, uvicorn, yt_dlp, pystray, PIL; print('imports ok, yt-dlp', yt_dlp.version.__version__)")
Run (Join-Path $Bin "ffmpeg.exe") @("-version")
Run (Join-Path $Bin "deno.exe") @("--version")
Run $Py @("-c", "import sys; sys.path.insert(0, r'$App'); import server; print('server ok, ffmpeg:', server.HAS_FFMPEG, 'deno:', server.HAS_DENO)")

# ---------------------------------------------------------------- 5. installer
$m = Select-String -Path (Join-Path $Root "local_app\server.py") -Pattern 'APP_VERSION = "([^"]+)"'
$AppVersion = $m.Matches[0].Groups[1].Value

# Also saved to a file, so compiling setup.iss by hand in the Inno Setup window uses the same values.
Set-Content -Path (Join-Path $PSScriptRoot "build_defines.iss") -Encoding UTF8 -Value @(
    "#define AppVersion `"$AppVersion`"",
    "#define SourceDir `"$App`"",
    "#define OutputDir `"$Dist`""
)

Step "Inno Setup (version $AppVersion)"
$iscc = Find-Iscc

if ($iscc) {
    Write-Host "   using $iscc"
    # Old installers (for example MediaCatcher-Setup-0.0.0.exe) are moved away so you never install a stale one by mistake.
    $oldSetups = Get-ChildItem $Dist -Filter "MediaCatcher-Setup-*.exe" -ErrorAction SilentlyContinue
    if ($oldSetups) {
        $oldDir = Join-Path $Dist "old"
        New-Item -ItemType Directory -Force -Path $oldDir | Out-Null
        $oldSetups | Move-Item -Force -Destination $oldDir
    }
    Run $iscc @("/DAppVersion=$AppVersion", "/DSourceDir=$App", "/DOutputDir=$Dist", (Join-Path $PSScriptRoot "setup.iss"))
    Write-Host ""
    # A copy with a fixed name (no version): this is the file the extension links to, so the
    # "latest release" download URL never changes.
    $versioned = Join-Path $Dist "MediaCatcher-Setup-$AppVersion.exe"
    Copy-Item $versioned (Join-Path $Dist "MediaCatcher-Setup.exe") -Force
    Write-Host "DONE: $versioned" -ForegroundColor Green
    Write-Host "      $Dist\MediaCatcher-Setup.exe  (same file, fixed name - upload this one to your release)" -ForegroundColor Green
} else {
    Write-Host "Inno Setup (ISCC.exe) was not found." -ForegroundColor Yellow
    Write-Host "  - Not installed?  Get Inno Setup 6.3 or newer: https://jrsoftware.org/isinfo.php"
    Write-Host "  - Installed somewhere else?  Run:  installer\build.bat -InnoPath ""C:\path\to\ISCC.exe"""
    Write-Host "  - Or compile by hand: open installer\setup.iss in Inno Setup and press Ctrl+F9."
    Write-Host "    (installer\build_defines.iss already holds the version and folders)"
    Write-Host ""
    Write-Host "The app folder is ready at: $App"
}