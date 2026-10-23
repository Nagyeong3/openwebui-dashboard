param(
    [string]$CondaExe = "$env:USERPROFILE\miniconda3\Scripts\conda.exe",
    [string]$OutputDirectory = "conda-bundle-v2",
    [string]$BuildPrefix = "$env:USERPROFILE\oui-dashboard-build-v2"
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'Run on Windows x64, matching the target servers.' }
if (-not (Test-Path -LiteralPath $CondaExe)) { throw 'Specify the installed Miniconda conda.exe with -CondaExe.' }
$version = & $CondaExe --version
if ($LASTEXITCODE -ne 0 -or "$version".Trim() -ne 'conda 26.7.1') { throw "Expected conda 26.7.1; got $version" }
if (Test-Path -LiteralPath $BuildPrefix) { throw 'BuildPrefix already exists. Choose a new, empty path; do not overwrite an environment.' }
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw 'OutputDirectory already exists. Choose a new directory.' }
New-Item -ItemType Directory -Path $output | Out-Null
Push-Location $root
try {
    & $CondaExe create --prefix $BuildPrefix --override-channels --channel https://repo.anaconda.com/pkgs/main --channel https://repo.anaconda.com/pkgs/r python=3.12 pip --yes
    if ($LASTEXITCODE -ne 0) { throw 'Conda environment creation failed.' }
    & $CondaExe run --no-capture-output --prefix $BuildPrefix python -m pip install -r backend_v2/requirements-test.txt -r backend_v2/requirements-pack.txt
    if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }
    & $CondaExe run --no-capture-output --prefix $BuildPrefix python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed.' }
    & $CondaExe run --no-capture-output --prefix $BuildPrefix python -m unittest discover -s backend_v2/tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed; archive not produced.' }
    & $CondaExe list --prefix $BuildPrefix --explicit | Set-Content -Encoding UTF8 (Join-Path $output 'conda-explicit-win64.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Conda manifest export failed.' }
    & $CondaExe run --prefix $BuildPrefix python -m pip freeze | Set-Content -Encoding UTF8 (Join-Path $output 'pip-freeze.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Pip manifest export failed.' }
    $archive = Join-Path $output 'oui-dashboard-v2-win64.zip'
    & $CondaExe run --no-capture-output --prefix $BuildPrefix python -c "import conda_pack,sys; conda_pack.pack(prefix=sys.argv[1], output=sys.argv[2], format='zip')" $BuildPrefix $archive
    if ($LASTEXITCODE -ne 0) { throw 'Environment packaging failed.' }
    Copy-Item -LiteralPath (Join-Path $root 'backend_v2') -Destination $output -Recurse
    Get-ChildItem (Join-Path $output 'backend_v2') -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  oui-dashboard-v2-win64.zip" | Set-Content -Encoding ASCII (Join-Path $output 'SHA256SUMS.txt')
    Write-Host "Ready: $output (environment, source, exact manifests, SHA256). No token/CSV/cache copied."
} finally { Pop-Location }
