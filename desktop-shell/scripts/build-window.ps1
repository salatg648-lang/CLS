$ErrorActionPreference = 'Stop'
$Root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $Root
if (-not (Test-Path '.venv-build\Scripts\python.exe')) {
    py -3 -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ wird benötigt.' }
}
$Python = "$Root\.venv-build\Scripts\python.exe"
& $Python -m pip install -r requirements.txt 'pyinstaller>=6.12,<7'
if ($LASTEXITCODE -ne 0) { throw 'Python-Abhängigkeiten konnten nicht installiert werden.' }
& $Python desktop-shell/scripts/build-core.py
if ($LASTEXITCODE -ne 0) { throw 'Core-Build fehlgeschlagen.' }
Set-Location desktop-shell
npm ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci fehlgeschlagen.' }
npm run package:win
if ($LASTEXITCODE -ne 0) { throw 'Windows-Paketierung fehlgeschlagen.' }
Write-Output 'Fertig: desktop-shell/release/CLS Setup 0.7.0.exe'
