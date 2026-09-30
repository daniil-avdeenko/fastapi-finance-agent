$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$image       = "finance-agent-pip-tools"
$cacheVolume = "finance-agent-pip-cache"

docker build -q -t $image -f scripts/requirements-compile.Dockerfile scripts | Out-Null

docker run --rm `
  -v "${PWD}:/work" `
  -v "${cacheVolume}:/root/.cache/pip" `
  -w /work `
  $image `
  bash scripts/_pip_compile.sh

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
