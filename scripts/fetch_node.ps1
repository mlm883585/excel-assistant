$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dir = Join-Path $root 'offline/node'
New-Item -ItemType Directory -Path $dir -Force | Out-Null
$exe = Join-Path $dir 'node.exe'
$version = 'v24.13.0'

if (Test-Path $exe) {
  $have = (& $exe --version)
  if ($have -eq $version) { Write-Output "node.exe $version already present"; exit 0 }
}

$zip = Join-Path $dir 'node-win-x64.zip'
Invoke-WebRequest "https://nodejs.org/dist/v24.13.0/node-v24.13.0-win-x64.zip" -OutFile $zip
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
  $entry = $archive.Entries | Where-Object { $_.FullName -like '*node.exe' } | Select-Object -First 1
  if (-not $entry) { throw 'node.exe not found in archive' }
  [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $exe, $true)
} finally {
  $archive.Dispose()
}
Remove-Item $zip -Force

$have = (& $exe --version)
if ($have -ne $version) { throw "node.exe version mismatch: $have (expected $version)" }
Get-FileHash $exe -Algorithm SHA256
Write-Output "node.exe $version placed at $exe"
