# Run a Taskfile task inside the forge container, e.g. `.\mf compile MAP=test_box`.
# --build keeps the image in sync with config/pipeline.yaml and uv.lock (cached, so cheap).
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "mf: Docker is not responding. Start Docker Desktop and try again."
    exit 125
}
docker compose -f "$PSScriptRoot\compose.yaml" run --rm --build --quiet-build forge task @args
exit $LASTEXITCODE
