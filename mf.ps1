# Run a Taskfile task inside the forge container, e.g. `.\mf compile MAP=test_box`.
# --build keeps the image in sync with config/pipeline.yaml and uv.lock (cached, so cheap).
docker compose -f "$PSScriptRoot\compose.yaml" run --rm --build --quiet-build forge task @args
exit $LASTEXITCODE
