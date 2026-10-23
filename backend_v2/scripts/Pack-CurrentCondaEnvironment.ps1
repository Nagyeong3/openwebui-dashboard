param(
    [string]$EnvironmentPrefix = $env:CONDA_PREFIX,
    [string]$OutputDirectory = 'conda-bundle-v2-r1'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'Run on Windows x64, matching the target servers.' }
if (-not $EnvironmentPrefix) { throw 'Activate oui-dashboard-v2 first, or specify -EnvironmentPrefix.' }
$prefix = (Resolve-Path -LiteralPath $EnvironmentPrefix).Path
if (-not (Test-Path -LiteralPath (Join-Path $prefix 'conda-meta'))) { throw 'Not a Conda environment.' }
if (Test-Path -LiteralPath (Join-Path $prefix 'conda-meta\history')) {
    if (Test-Path -LiteralPath (Join-Path $prefix 'condabin\conda.bat')) { throw 'Do not pack base. Activate the application environment.' }
}
$python = Join-Path $prefix 'python.exe'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw 'OutputDirectory already exists. Choose a new output directory.' }
Push-Location $root
try {
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed.' }
    & $python -m unittest discover -s backend_v2/tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed; archive not produced.' }
    & $python -c 'import conda_pack'
    if ($LASTEXITCODE -ne 0) { throw 'Install backend_v2/requirements-pack.txt in this environment first.' }
    New-Item -ItemType Directory -Path $output | Out-Null
    $archive = Join-Path $output 'oui-dashboard-v2-win64.zip'
    & $python -c "import conda_pack,sys; conda_pack.pack(prefix=sys.argv[1], output=sys.argv[2], format='zip')" $prefix $archive
    if ($LASTEXITCODE -ne 0) { throw 'Environment packaging failed.' }
    Copy-Item -LiteralPath (Join-Path $root 'backend_v2') -Destination $output -Recurse
    Get-ChildItem (Join-Path $output 'backend_v2') -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    & $python -m pip freeze | Set-Content -Encoding UTF8 (Join-Path $output 'pip-freeze.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Manifest export failed.' }
    Copy-Item -LiteralPath (Join-Path $prefix 'conda-meta\history') -Destination (Join-Path $output 'conda-history.txt')
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  oui-dashboard-v2-win64.zip" | Set-Content -Encoding ASCII (Join-Path $output 'SHA256SUMS.txt')
    Write-Host "Ready: $output. Transfer this complete folder. Tokens, CSV and cache are not included."
} finally { Pop-Location }
