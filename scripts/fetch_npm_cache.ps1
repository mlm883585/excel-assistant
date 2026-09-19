$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$cache = Join-Path $root 'offline/npm'
New-Item -ItemType Directory -Path $cache -Force | Out-Null

# Populate the npm cache for both lockfiles. `npm ci` also (re)installs
# node_modules, both gitignored. On the intranet, install with:
#   npm ci --offline --ignore-scripts --cache offline/npm
#   npm ci --prefix gui --offline --ignore-scripts --cache offline/npm
npm ci --ignore-scripts --cache $cache
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm ci --prefix gui --ignore-scripts --cache $cache
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "npm offline cache populated at $cache"
