"""Baseline eval harness — runs bot/analyzer.py's REAL Claude/Tavily pipeline
against fixed fixtures, with zero changes to bot/ production code.

Instrumentation strategy: monkeypatch only the network boundary
(anthropic_client.messages.create, tavily_client.search, requests.get for
LINE image download), always calling through to the real implementation and
just recording latency/usage as a side effect. bot/analyzer.py's own logic
is never touched or replaced.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import bot.analyzer as analyzer_module
import bot.state as state_module

from evals.cases import EvalCase

REPO_ROOT = Path(__file__).parent.parent

# 待確認 Anthropic 官方即時 pricing 後再填入（USD / million tokens）。
# 使用前務必核對 https://www.anthropic.com/pricing 的當下數字，不要用記憶中的舊值。
PRICING_PER_MTOK: dict[str, dict[str, float | None]] = {
    "claude-sonnet-5": {"input": None, "output": None},
}

FAKE_STATE_USER_ID = "eval-harness-user"


# ---------------------------------------------------------------------------
# Network-boundary wrappers (call through to the real implementation)
# ---------------------------------------------------------------------------

def _make_claude_wrapper(call_log: list[dict]) -> Callable:
    original_create = analyzer_module.anthropic_client.messages.create

    def wrapper(*args, **kwargs):
        # SYSTEM_PROMPT 本文自己就會提到「收到 OUTPUT=BRIEF」「收到 OUTPUT=FULL」
        # 這兩個字面字串（用來跟模型說明兩種模式），所以不能用 "in" 判斷──
        # 那樣兩種字串在每一通呼叫裡都存在。實際決定模式的是附加在字串「結尾」
        # 的 "\nOUTPUT=BRIEF" / "\nOUTPUT=FULL"（見 bot/analyzer.py），只能用
        # endswith 判斷。
        system_text = kwargs.get("system", "") or ""
        stripped = system_text.rstrip()
        if stripped.endswith("OUTPUT=FULL"):
            output_mode = "FULL"
        elif stripped.endswith("OUTPUT=BRIEF"):
            output_mode = "BRIEF"
        else:
            output_mode = "UNKNOWN"

        start = time.perf_counter()
        response = original_create(*args, **kwargs)
        elapsed = time.perf_counter() - start

        usage = getattr(response, "usage", None)
        call_log.append({
            "model": kwargs.get("model"),
            "output_mode": output_mode,
            "stop_reason": getattr(response, "stop_reason", None),
            "elapsed_s": elapsed,
            "input_tokens": getattr(usage, "input_tokens", None) if usage else None,
            "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
        })
        return response

    return wrapper


def _make_tavily_wrapper(tavily_log: list[dict]) -> Callable:
    original_search = analyzer_module.tavily_client.search

    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = original_search(*args, **kwargs)
        elapsed = time.perf_counter() - start

        query = args[0] if args else kwargs.get("query")
        num_results = None
        if isinstance(result, dict):
            num_results = len(result.get("results", []))
        tavily_log.append({
            "query": query,
            "elapsed_s": elapsed,
            "num_results": num_results,
        })
        return result

    return wrapper


def _make_fake_image_response(image_bytes: bytes) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.content = image_bytes
    mock_resp.raise_for_status = lambda: None
    return mock_resp


# ---------------------------------------------------------------------------
# Hard checks (mechanical, not subjective quality grading)
# ---------------------------------------------------------------------------

_MARKDOWN_BOLD_RE = re.compile(r"\*\*.+?\*\*", re.DOTALL)
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,3} ", re.MULTILINE)


def check_basic_shape(ctx: dict) -> dict:
    result = ctx.get("result") or {}
    brief = result.get("brief")
    full = result.get("full")
    problems = []

    if not brief or not isinstance(brief, str):
        problems.append("brief 為空或非字串")
    if not full or not isinstance(full, str):
        problems.append("full 為空或非字串")

    # analyze_image() 內部有 bare except，任何例外（包括 API 400/500、額度
    # 不足等）都會被靜默吞掉、改回傳 ERROR_BRIEF/ERROR_FULL——外觀跟正常回覆
    # 一樣是非空字串，basic_shape 若只檢查「有沒有字」會誤判成通過。這裡直接
    # 比對該 sentinel 值，讓真正的管線失敗現形，不要被當成一次成功的模型輸出。
    if brief == analyzer_module.ERROR_BRIEF or full == analyzer_module.ERROR_FULL:
        problems.append(
            "疑似靜默失敗：analyze_image() 內部例外被吞掉，回傳的是 ERROR_BRIEF/ERROR_FULL "
            "而非真實模型輸出（常見原因：API 額度不足、圖片格式錯誤等）"
        )

    for text, label in ((brief, "brief"), (full, "full")):
        if not isinstance(text, str):
            continue
        if "NOT_RELEVANT:" in text:
            problems.append(f"{label} 殘留 NOT_RELEVANT: 前綴")
        if _MARKDOWN_BOLD_RE.search(text):
            problems.append(f"{label} 殘留 ** 粗體符號")
        if "```" in text:
            problems.append(f"{label} 殘留 ``` 程式碼區塊")
        if _MARKDOWN_HEADING_RE.search(text):
            problems.append(f"{label} 殘留 # 標題符號")

    return {"passed": len(problems) == 0, "detail": "; ".join(problems) or "ok"}


def check_equals_not_found(ctx: dict) -> dict:
    result = ctx.get("result") or {}
    passed = (
        result.get("brief") == analyzer_module.NOT_FOUND_BRIEF
        and result.get("full") == analyzer_module.NOT_FOUND_FULL
    )
    detail = "ok" if passed else f"實際輸出（前 80 字）：{str(result.get('brief', ''))[:80]}"
    return {"passed": passed, "detail": detail}


def check_state_roundtrip_match(ctx: dict) -> dict:
    fed_in = ctx.get("fed_in")
    retrieved = ctx.get("retrieved")
    passed = retrieved == fed_in and fed_in is not None
    detail = "ok" if passed else "讀出值與餵入值不同，或餵入值為空"
    return {"passed": passed, "detail": detail}


HARD_CHECKS: dict[str, Callable[[dict], dict]] = {
    "basic_shape": check_basic_shape,
    "equals_not_found": check_equals_not_found,
    "state_roundtrip_match": check_state_roundtrip_match,
}


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_record(case: EvalCase, run_index: int) -> dict:
    return {
        "case_id": case.case_id,
        "run_index": run_index,
        "category": case.category,
        "call_target": case.call_target,
        "purpose": case.purpose,
        "brief_text": None,
        "full_text": None,
        "total_latency_s": None,
        "total_input_tokens": None,
        "total_output_tokens": None,
        "num_claude_calls": 0,
        "call_log": [],
        "num_tavily_calls": 0,
        "tavily_log": [],
        "estimated_cost_usd": None,
        "hard_check_results": {},
        "error": None,
        "skipped": False,
        "skip_reason": None,
        "timestamp_utc": _now_iso(),
    }


def _skipped_record(case: EvalCase, run_index: int, reason: str) -> dict:
    rec = _base_record(case, run_index)
    rec["skipped"] = True
    rec["skip_reason"] = reason
    return rec


def _sum_tokens(call_log: list[dict], key: str) -> int | None:
    values = [c[key] for c in call_log if c.get(key) is not None]
    return sum(values) if values else None


# ---------------------------------------------------------------------------
# Per-case runners
# ---------------------------------------------------------------------------

def run_text_case(case: EvalCase, run_index: int) -> dict:
    call_log: list[dict] = []
    tavily_log: list[dict] = []
    rec = _base_record(case, run_index)

    try:
        with patch.object(
            analyzer_module.anthropic_client.messages, "create",
            side_effect=_make_claude_wrapper(call_log),
        ), patch.object(
            analyzer_module.tavily_client, "search",
            side_effect=_make_tavily_wrapper(tavily_log),
        ):
            start = time.perf_counter()
            result = analyzer_module.analyze_product_name(case.text_input)
            total_latency_s = time.perf_counter() - start
    except Exception as e:  # noqa: BLE001 — baseline run must not abort on one bad case
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["call_log"] = call_log
        rec["tavily_log"] = tavily_log
        rec["num_claude_calls"] = len(call_log)
        rec["num_tavily_calls"] = len(tavily_log)
        return rec

    rec["brief_text"] = result.get("brief")
    rec["full_text"] = result.get("full")
    rec["total_latency_s"] = total_latency_s
    rec["total_input_tokens"] = _sum_tokens(call_log, "input_tokens")
    rec["total_output_tokens"] = _sum_tokens(call_log, "output_tokens")
    rec["num_claude_calls"] = len(call_log)
    rec["call_log"] = call_log
    rec["num_tavily_calls"] = len(tavily_log)
    rec["tavily_log"] = tavily_log

    ctx = {"result": result}
    rec["hard_check_results"] = {
        name: HARD_CHECKS[name](ctx) for name in case.hard_checks
    }
    rec["_result"] = result  # kept in-memory only, for D1's dependency; stripped before writing to disk
    return rec


def run_image_case(case: EvalCase, run_index: int) -> dict:
    if case.image_path is None or not case.image_path.exists():
        return _skipped_record(
            case, run_index,
            f"缺圖片：預期路徑 {case.image_path}",
        )

    call_log: list[dict] = []
    rec = _base_record(case, run_index)
    image_bytes = case.image_path.read_bytes()
    fake_response = _make_fake_image_response(image_bytes)

    try:
        with patch.object(
            analyzer_module.anthropic_client.messages, "create",
            side_effect=_make_claude_wrapper(call_log),
        ), patch("bot.analyzer.requests.get", return_value=fake_response):
            start = time.perf_counter()
            result = analyzer_module.analyze_image(f"eval-{case.case_id}-{run_index}")
            total_latency_s = time.perf_counter() - start
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["call_log"] = call_log
        rec["num_claude_calls"] = len(call_log)
        return rec

    rec["brief_text"] = result.get("brief")
    rec["full_text"] = result.get("full")
    rec["total_latency_s"] = total_latency_s
    rec["total_input_tokens"] = _sum_tokens(call_log, "input_tokens")
    rec["total_output_tokens"] = _sum_tokens(call_log, "output_tokens")
    rec["num_claude_calls"] = len(call_log)
    rec["call_log"] = call_log

    ctx = {"result": result}
    rec["hard_check_results"] = {
        name: HARD_CHECKS[name](ctx) for name in case.hard_checks
    }
    rec["_result"] = result
    return rec


def run_state_roundtrip_case(case: EvalCase, run_index: int, prior_results: dict) -> dict:
    rec = _base_record(case, run_index)
    dep_record = prior_results.get((case.depends_on, run_index))

    if dep_record is None or dep_record.get("skipped") or dep_record.get("error"):
        return _skipped_record(
            case, run_index,
            f"依賴案例 {case.depends_on}（同輪 run_index={run_index}）沒有可用結果",
        )

    fed_in = dep_record.get("full_text")
    start = time.perf_counter()
    state_module.save_full_analysis(FAKE_STATE_USER_ID, fed_in)
    retrieved = state_module.get_full_analysis(FAKE_STATE_USER_ID)
    state_module.clear_analysis(FAKE_STATE_USER_ID)
    rec["total_latency_s"] = time.perf_counter() - start
    rec["brief_text"] = fed_in
    rec["full_text"] = retrieved

    ctx = {"fed_in": fed_in, "retrieved": retrieved}
    rec["hard_check_results"] = {
        name: HARD_CHECKS[name](ctx) for name in case.hard_checks
    }
    return rec


def run_case(case: EvalCase, run_index: int, prior_results: dict) -> dict:
    if case.call_target == "analyze_product_name":
        rec = run_text_case(case, run_index)
    elif case.call_target == "analyze_image":
        rec = run_image_case(case, run_index)
    elif case.call_target == "state_roundtrip":
        rec = run_state_roundtrip_case(case, run_index, prior_results)
    else:
        raise ValueError(f"unknown call_target: {case.call_target}")

    prior_results[(case.case_id, run_index)] = rec
    return rec


def strip_internal_fields(record: dict) -> dict:
    """Drop in-memory-only helper fields (e.g. `_result`) before writing to disk."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------

def get_git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


def compute_cases_fingerprint(cases: list[EvalCase]) -> str:
    canonical = [
        {
            "case_id": c.case_id,
            "category": c.category,
            "call_target": c.call_target,
            "text_input": c.text_input,
            "image_path": str(c.image_path) if c.image_path else None,
            "depends_on": c.depends_on,
        }
        for c in cases
    ]
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def detect_models_used(records: list[dict]) -> list[str]:
    """Derive the actual model name(s) observed in call_log entries, rather than
    hardcoding it in run_baseline.py — bot/analyzer.py's model string can change
    (e.g. claude-sonnet-4-6 → claude-sonnet-5) and meta.json should always
    reflect what was really called, not a stale literal."""
    models = {
        c.get("model")
        for r in records
        for c in r.get("call_log", [])
        if c.get("model")
    }
    return sorted(models)


def get_anthropic_sdk_version() -> str | None:
    try:
        import anthropic
        return getattr(anthropic, "__version__", None)
    except Exception:
        return None
