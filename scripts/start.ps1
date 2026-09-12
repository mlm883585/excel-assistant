$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & "$projectRoot\.venv\Scripts\python.exe" "$projectRoot\main.py"
    if ($LASTEXITCODE -ne 0) { throw '桌面应用启动失败，请运行 scripts/doctor.py' }
} finally { Pop-Location }
