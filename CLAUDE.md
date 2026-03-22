# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git 規範
- 不要自動執行 git commit
- 需要 commit 時，列出準備 commit 的檔案和建議的 commit message，等我確認後再執行

## Project Overview

EDC Analysis LINE Bot — a LINE chatbot that analyzes personal care products for endocrine-disrupting chemicals (EDCs). Users send product photos (ingredient labels) or text (product names) and receive risk assessments in Taiwanese Mandarin. Deployed on Railway.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run tests
pytest tests/ -v --tb=short

# Run a single test file or test
pytest tests/test_analyzer.py -v
pytest tests/test_main.py -v -k "test_verify_signature"

# Local dev server
uvicorn bot.main:app --host 0.0.0.0 --port 8000
```

## Architecture

Four modules in `bot/`:

- **main.py** — FastAPI app with `/webhook` (LINE webhook) and `/health` endpoints. Verifies LINE signature via HMAC-SHA256, dispatches message processing as background tasks, sends responses via LINE Push API (not Reply API, due to 60s token expiry).

- **analyzer.py** — Core analysis logic with two flows:
  - `analyze_image()`: Downloads LINE image → resizes with Pillow → base64 encodes → sends to Claude Vision for EDC analysis
  - `analyze_product_name()`: Tool-use loop (max 3 rounds) with Tavily web search to find INCI ingredients, then Claude analysis. Brief search context is reused for the full analysis call to avoid redundant Tavily queries.
  - Both return `{"brief": ..., "full": ...}` dicts. Markdown is stripped from responses via `_strip_markdown()`.

- **prompts.py** — `EDC_SYSTEM_PROMPT` defining the 6 EDC categories, risk framework, and output format (BRIEF vs FULL). `DETAIL_TRIGGERS` set for follow-up keywords ("詳細", "详细", etc.).

- **state.py** — In-memory dict storing full analysis per user_id for "詳細" follow-up queries. State is lost on restart.

## Key Design Decisions

- Uses Claude `claude-sonnet-4-6` for both vision and text analysis
- Two-tier output: BRIEF (quick checklist) sent immediately, FULL stored and retrieved via "詳細" trigger
- `OUTPUT=BRIEF` / `OUTPUT=FULL` appended to system prompt to control response format
- Prompt explicitly forbids Markdown output (LINE renders plain text only)
- Image resizing: 1600px max, falls back to 800px if >3.5MB after first pass

## Environment Variables

Required (see `.env.example`): `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`, `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`

## Language

All user-facing text and prompts are in Traditional Chinese (繁體中文). Code comments and variable names are in English.
