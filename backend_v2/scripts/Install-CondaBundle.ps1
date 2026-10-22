param(
    [Parameter(Mandatory=$true)][string]$BundleDirectory,
    [Parameter(Mandatory=$true)][string]$EnvironmentPrefix
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'This bundle requires Windows x64.' }
$bundle = (Resolve-Path -LiteralPath $BundleDirectory).Path
$target = [IO.Path]::GetFullPath($EnvironmentPrefix)
if (Test-Path -LiteralPath $target) { throw 'EnvironmentPrefix already exists. Use a new, final destination path.' }
$archive = Join-Path $bundle 'oui-dashboard-v2-win64.zip'
$expected = ((Get-Content -LiteralPath (Join-Path $bundle 'SHA256SUMS.txt') -Raw).Trim() -split '\s+')[0]
if ($expected -notmatch '^[0-9a-fA-F]{64}$') { throw 'Invalid checksum manifest.' }
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'Archive checksum mismatch.' }
Expand-Archive -LiteralPath $archive -DestinationPath $target
$python = Join-Path $target 'python.exe'
$unpack = Join-Path $target 'Scripts\conda-unpack-script.py'
if (-not (Test-Path -LiteralPath $unpack)) { throw 'Missing conda-unpack script; bundle is incomplete.' }
# Add DLL locations before Python startup; no conda init/profile changes required.
$oldPath = $env:PATH
try {
    $env:PATH = "$target;$target\Scripts;$target\Library\bin;$oldPath"
    & $python $unpack
    if ($LASTEXITCODE -ne 0) { throw 'Conda prefix repair failed; do not use this extracted environment.' }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed.' }
    Push-Location $bundle
    try {
        & $python -m unittest discover -s backend_v2/tests -v
        if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed on target.' }
    } finally { Pop-Location }
    Write-Host "Installed: $target. Keep this path fixed. Activate with conda activate $target."
} finally { $env:PATH = $oldPath }
