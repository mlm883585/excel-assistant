$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$mediaRoot = Join-Path $projectRoot 'runtime'
New-Item -ItemType Directory -Path $mediaRoot -Force | Out-Null
$installer = Join-Path $mediaRoot 'WebView2StandaloneX64.exe'
Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124701' -OutFile $installer
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
    throw 'WebView2 安装介质签名验证失败，拒绝交付'
}
Get-FileHash -LiteralPath $installer -Algorithm SHA256
