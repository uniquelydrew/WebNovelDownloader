param(
    [string]$Python = ".venv\Scripts\python.exe",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonPath = Join-Path $ProjectRoot $Python
if (-not (Test-Path $PythonPath)) {
    throw "Python executable not found: $PythonPath"
}

$BrowserRoot = Join-Path $ProjectRoot ".playwright-browsers"
$env:PLAYWRIGHT_BROWSERS_PATH = $BrowserRoot

Push-Location $ProjectRoot
try {
    & $PythonPath -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

    & $PythonPath -m pip install -r requirements.txt -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

    & $PythonPath -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "playwright browser install failed" }

    $pyInstallerArgs = @("-m", "PyInstaller")
    if ($Clean) {
        $pyInstallerArgs += "--clean"
    }
    $pyInstallerArgs += @("--noconfirm", "WebNovelScraper.spec")

    & $PythonPath @pyInstallerArgs
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
}
finally {
    Pop-Location
}
