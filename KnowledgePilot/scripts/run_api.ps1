$env:KP_USE_OLLAMA = "true"
$env:KP_OLLAMA_MODEL = if ($env:KP_OLLAMA_MODEL) { $env:KP_OLLAMA_MODEL } else { "qwen2.5:7b" }
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
