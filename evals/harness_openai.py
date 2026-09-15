"""Baseline eval harness — OpenAI Responses API counterpart to evals/harness.py.

Same instrumentation strategy: monkeypatch only the network boundary
(openai_client.responses.create, tavily_client.search, requests.get), always
calling through to the real implementation. bot/analyzer_openai.py's own
logic is never touched or replaced.

Reuses evals/harness.py wherever the logic is provider-agnostic (Tavily
wrapper, HARD_CHECKS, record helpers, git/fingerprint metadata) rather than
duplicating it — see plan section 5.1.
"""

from __future__ import annotations

import time
from typing import Callable
from unittest.mock import patch

import bot.analyzer as analyzer_module
import bot.analyzer_openai as analyzer_openai_module
import bot.state_openai as state_openai_module

from evals import harness
from evals.cases import EvalCase

FAKE_STATE_USER_ID = harness.FAKE_STATE_USER_ID

# 待確認 OpenAI 官方即時 pricing 後再填入（USD / million tokens）。
# 使用前務必核對 https://openai.com/api/pricing 的當下數字，不要用記憶中的舊值。
PRICING_PER_MTOK_OPENAI: dict[str, dict[str, float | None]] = {
    "gpt-5.6-terra": {"input": None, "output": None},
}


# ---------------------------------------------------------------------------
# Network-boundary wrappers
# ---------------------------------------------------------------------------

def _make_openai_wrapper(call_log: list[dict]) -> Callable:
    original_create = analyzer_openai_module.openai_client.responses.create

    def wrapper(*args, **kwargs):
        instructions = kwargs.get("instructions", "") or ""
        stripped = instructions.rstrip()
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
            "elapsed_s": elapsed,
            "input_tokens": getattr(usage, "input_tokens", None) if usage else None,
            "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
        })
        return response

    return wrapper


def _materialize_full_text(full_response_id: str | None, brief_text: str | None) -> tuple[str | None, list[dict]]:
    """Fetch FULL text back via retrieve() for eval reporting/hard-check
    purposes — independent of state_openai.py (which the real webhook flow
    uses), this is the harness's own reference read.

    Falls back to the NOT_FOUND sentinel when there's no response to
    retrieve (the tool loop exhausted MAX_ROUNDS without a real analysis),
    mirroring the shape Claude's harness sees — both brief/full populated —
    so check_basic_shape's "both non-empty" assumption still holds for that
    boundary case instead of flagging a false problem.
    """
    retrieve_log: list[dict] = []
    if full_response_id is None:
        if brief_text == analyzer_openai_module.NOT_FOUND_BRIEF:
            return analyzer_module.NOT_FOUND_FULL, retrieve_log
        return None, retrieve_log

    start = time.perf_counter()
    retrieved = analyzer_openai_module.openai_client.responses.retrieve(full_response_id)
    elapsed = time.perf_counter() - start
    usage = getattr(retrieved, "usage", None)
    retrieve_log.append({
        "elapsed_s": elapsed,
        "input_tokens": getattr(usage, "input_tokens", None) if usage else None,
        "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
    })
    return retrieved.output_text, retrieve_log


# ---------------------------------------------------------------------------
# OpenAI-specific hard check: D1's state_roundtrip, via retrieve() not
# a Claude-style exact-text roundtrip (see plan section 5.2).
# ---------------------------------------------------------------------------

def check_retrieve_roundtrip_match(ctx: dict) -> dict:
    original_full_text = ctx.get("original_full_text")
    retrieved_full_text = ctx.get("retrieved_full_text")
    passed = retrieved_full_text == original_full_text and original_full_text is not None
    detail = "ok" if passed else "retrieve() 讀回的內容跟生成當下算出來的內容不一致，或原始內容為空"
    return {"passed": passed, "detail": detail}


# Same HARD_CHECKS as the Claude harness, except "state_roundtrip_match" is
# swapped for the retrieve-based check above. cases.py's D1 definition
# (hard_checks=("state_roundtrip_match",)) is untouched — this dict just
# resolves that same key to the OpenAI-appropriate check function.
HARD_CHECKS_OPENAI: dict[str, Callable[[dict], dict]] = {
    **harness.HARD_CHECKS,
    "state_roundtrip_match": check_retrieve_roundtrip_match,
}


# ---------------------------------------------------------------------------
# Per-case runners
# ---------------------------------------------------------------------------

def run_text_case_openai(case: EvalCase, run_index: int) -> dict:
    call_log: list[dict] = []
    tavily_log: list[dict] = []
    rec = harness._base_record(case, run_index)

    try:
        with patch.object(
            analyzer_openai_module.openai_client.responses, "create",
            side_effect=_make_openai_wrapper(call_log),
        ), patch.object(
            analyzer_module.tavily_client, "search",
            side_effect=harness._make_tavily_wrapper(tavily_log),
        ):
            start = time.perf_counter()
            result = analyzer_openai_module.analyze_product_name_openai(case.text_input)
            gen_latency_s = time.perf_counter() - start
    except Exception as e:  # noqa: BLE001 — baseline run must not abort on one bad case
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["call_log"] = call_log
        rec["tavily_log"] = tavily_log
        rec["num_claude_calls"] = len(call_log)
        rec["num_tavily_calls"] = len(tavily_log)
        return rec

    brief_text = result.get("brief")
    full_response_id = result.get("full")
    full_text, retrieve_log = _materialize_full_text(full_response_id, brief_text)

    rec["brief_text"] = brief_text
    rec["full_text"] = full_text
    rec["retrieve_log"] = retrieve_log
    rec["total_latency_s"] = gen_latency_s + sum(r["elapsed_s"] for r in retrieve_log)
    rec["total_input_tokens"] = harness._sum_tokens(call_log, "input_tokens")
    rec["total_output_tokens"] = harness._sum_tokens(call_log, "output_tokens")
    rec["num_claude_calls"] = len(call_log)
    rec["call_log"] = call_log
    rec["num_tavily_calls"] = len(tavily_log)
    rec["tavily_log"] = tavily_log

    ctx = {"result": {"brief": brief_text, "full": full_text}}
    rec["hard_check_results"] = {
        name: HARD_CHECKS_OPENAI[name](ctx) for name in case.hard_checks
    }
    rec["_full_response_id"] = full_response_id  # kept in-memory only, for D1's dependency; stripped before writing to disk
    return rec


def run_image_case_openai(case: EvalCase, run_index: int) -> dict:
    if case.image_path is None or not case.image_path.exists():
        return harness._skipped_record(
            case, run_index,
            f"缺圖片：預期路徑 {case.image_path}",
        )

    call_log: list[dict] = []
    rec = harness._base_record(case, run_index)
    image_bytes = case.image_path.read_bytes()
    fake_response = harness._make_fake_image_response(image_bytes)

    try:
        with patch.object(
            analyzer_openai_module.openai_client.responses, "create",
            side_effect=_make_openai_wrapper(call_log),
        ), patch("bot.analyzer.requests.get", return_value=fake_response):
            start = time.perf_counter()
            result = analyzer_openai_module.analyze_image_openai(f"eval-{case.case_id}-{run_index}")
            gen_latency_s = time.perf_counter() - start
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["call_log"] = call_log
        rec["num_claude_calls"] = len(call_log)
        return rec

    brief_text = result.get("brief")
    full_response_id = result.get("full")
    full_text, retrieve_log = _materialize_full_text(full_response_id, brief_text)

    rec["brief_text"] = brief_text
    rec["full_text"] = full_text
    rec["retrieve_log"] = retrieve_log
    rec["total_latency_s"] = gen_latency_s + sum(r["elapsed_s"] for r in retrieve_log)
    rec["total_input_tokens"] = harness._sum_tokens(call_log, "input_tokens")
    rec["total_output_tokens"] = harness._sum_tokens(call_log, "output_tokens")
    rec["num_claude_calls"] = len(call_log)
    rec["call_log"] = call_log

    ctx = {"result": {"brief": brief_text, "full": full_text}}
    rec["hard_check_results"] = {
        name: HARD_CHECKS_OPENAI[name](ctx) for name in case.hard_checks
    }
    rec["_full_response_id"] = full_response_id
    return rec


def run_state_roundtrip_case_openai(case: EvalCase, run_index: int, prior_results: dict) -> dict:
    rec = harness._base_record(case, run_index)
    dep_record = prior_results.get((case.depends_on, run_index))

    if dep_record is None or dep_record.get("skipped") or dep_record.get("error"):
        return harness._skipped_record(
            case, run_index,
            f"依賴案例 {case.depends_on}（同輪 run_index={run_index}）沒有可用結果",
        )

    full_response_id = dep_record.get("_full_response_id")
    original_full_text = dep_record.get("full_text")

    if not full_response_id:
        return harness._skipped_record(
            case, run_index,
            f"依賴案例 {case.depends_on} 沒有可用的 response id（NOT_FOUND 邊界情況沒有東西可以 retrieve）",
        )

    start = time.perf_counter()
    state_openai_module.save_full_analysis(FAKE_STATE_USER_ID, full_response_id)
    retrieved_full_text = state_openai_module.get_full_analysis(FAKE_STATE_USER_ID)
    state_openai_module.clear_analysis(FAKE_STATE_USER_ID)
    rec["total_latency_s"] = time.perf_counter() - start
    rec["brief_text"] = original_full_text
    rec["full_text"] = retrieved_full_text

    ctx = {"original_full_text": original_full_text, "retrieved_full_text": retrieved_full_text}
    rec["hard_check_results"] = {
        name: HARD_CHECKS_OPENAI[name](ctx) for name in case.hard_checks
    }
    return rec


def run_case_openai(case: EvalCase, run_index: int, prior_results: dict) -> dict:
    if case.call_target == "analyze_product_name":
        rec = run_text_case_openai(case, run_index)
    elif case.call_target == "analyze_image":
        rec = run_image_case_openai(case, run_index)
    elif case.call_target == "state_roundtrip":
        rec = run_state_roundtrip_case_openai(case, run_index, prior_results)
    else:
        raise ValueError(f"unknown call_target: {case.call_target}")

    prior_results[(case.case_id, run_index)] = rec
    return rec


def strip_internal_fields(record: dict) -> dict:
    return harness.strip_internal_fields(record)


# ---------------------------------------------------------------------------
# Run metadata — reuse what's provider-agnostic, add an OpenAI SDK version getter
# ---------------------------------------------------------------------------

get_git_commit = harness.get_git_commit
compute_cases_fingerprint = harness.compute_cases_fingerprint
detect_models_used = harness.detect_models_used


def get_openai_sdk_version() -> str | None:
    try:
        import openai
        return getattr(openai, "__version__", None)
    except Exception:
        return None
