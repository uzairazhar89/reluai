# 0005. LLM provider chain and token budget

Date: 2026-10-04. Status: accepted.

## Context

AI demos need a capable model, but the API budget is zero and every demo must keep working
if a free tier is exhausted or a provider is down. The site must never silently start
spending money.

## Decision

`packages/inference` exposes one OpenAI-compatible chat interface backed by a chain:

1. Groq free tier (fast and answer models).
2. Cerebras free tier, if a key is configured.
3. A local llama.cpp server (optional `llm` Compose profile, CPU only).
4. A deterministic provider that returns a clearly labelled, rule-based answer.

A provider is skipped on rate limits, outages or missing configuration; bad requests are not
retried elsewhere. A token ledger in PostgreSQL enforces a daily budget per provider, keeps
a reserve for scheduled showcase runs and caps each visitor. Tool calls are validated
against Pydantic schemas before anything executes. No paid provider is configured.

## Consequences

- Demos degrade in quality, never in availability, and the page says which provider
  answered.
- Free-tier limits are respected by construction, not by hope.
- Adding a paid provider would require changing configuration deliberately and is out of
  scope for this site.
