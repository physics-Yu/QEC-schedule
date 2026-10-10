# No PATH dependence: the default Anaconda Python is unsupported.
$ErrorActionPreference = 'Stop'
$naRoot = Split-Path $PSScriptRoot -Parent
$naPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $naPython)) {
    $naPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
}
if (-not (Test-Path -LiteralPath $naPython)) { throw 'Python >=3.12 missing; see knowledge/roles/R7/environment.md' }
$naPreviousPath = $env:PYTHONPATH
$naPreviousEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONPATH = (Join-Path $naRoot 'src') + [IO.Path]::PathSeparator + $naRoot
    $env:PYTHONIOENCODING = 'utf-8'
    & $naPython -m na_pipeline @args
    $naExit = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $naPreviousPath
    $env:PYTHONIOENCODING = $naPreviousEncoding
}
exit $naExit
