# Local LLM (optional)

The AI demos use free hosted models first (ADR-0005). A small local model on the server is
an optional fallback when the free tiers are exhausted or down. It runs on CPU with
llama.cpp in the `llm` Compose profile, limited to 2 GB of memory and 1.5 CPUs.

No live project needs it yet; enable it when the first AI project goes live.

## Choose a model

Use an instruction-tuned model of about 1 to 4 billion parameters in GGUF format, quantised
to Q4_K_M, with a licence that allows this use (record it in `artifacts/manifest.yaml`
first, ADR-0004). At this size expect a few tokens per second on two shared cores: fine as
a fallback for short answers, not as the primary model.

## Install

```bash
cd /opt/reluai/infra/compose
# Download into the models volume as model.gguf (the path the service expects)
docker run --rm -v reluai_models:/models alpine:3 \
  wget -O /models/model.gguf "<direct GGUF download URL>"
docker run --rm -v reluai_models:/models alpine:3 sha256sum /models/model.gguf   # compare with the manifest
```

Enable it in `.env`:

```
RELUAI_LLM_LOCAL_ENABLED=true
```

Start it with the profile and restart the API and worker so they pick up the setting:

```bash
docker compose -f compose.yaml -f compose.prod.yaml --profile llm up -d llm
docker compose -f compose.yaml -f compose.prod.yaml up -d api worker
```

## Check

```bash
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://llm:8080/health').read())"
```

## Disable

Set `RELUAI_LLM_LOCAL_ENABLED=false`, restart api and worker, then
`docker compose --profile llm stop llm`. The chain falls through to the deterministic
provider when no model is available.
