"""CLI entry point for the OpenAI Responses API baseline eval harness.

    python -m evals.run_baseline_openai --dry-run
    python -m evals.run_baseline_openai --cases A1 --n 1
    python -m evals.run_baseline_openai --n 3 --label tier1-textonly

跑的是 bot/analyzer_openai.py 現有、未修改的 OpenAI Responses API／Tavily pipeline，
會真的打 OpenAI／Tavily API（除了 --dry-run）。正式全量跑之前，建議先用
--dry-run 確認接線，再用 --cases A1 --n 1 驗證 harness 本身沒 bug。

結構完全比照 evals/run_baseline.py（Claude 版），方便兩份結果事後合併分析。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from evals.cases import CASES, CASES_BY_ID, TEXT_CASE_IDS  # noqa: E402
from evals import harness_openai as harness  # noqa: E402

RESULTS_DIR = Path(__file__).parent / "results"


def _resolve_selected_cases(case_ids: list[str]):
    unknown = [cid for cid in case_ids if cid not in CASES_BY_ID]
    if unknown:
        raise SystemExit(f"未知的 case id：{', '.join(unknown)}（可用：{', '.join(CASES_BY_ID)}）")
    selected_ids = set(case_ids)
    return [c for c in CASES if c.case_id in selected_ids]


def _print_dry_run(selected_cases) -> None:
    print("=== DRY RUN：不會呼叫任何真實 API ===\n")
    for c in selected_cases:
        if c.call_target == "analyze_image":
            input_desc = f"image_path={c.image_path}"
            if not (c.image_path and c.image_path.exists()):
                input_desc += "  [會被跳過：檔案不存在]"
        elif c.call_target == "state_roundtrip":
            input_desc = f"depends_on={c.depends_on}（重用同輪結果的 response id，透過 retrieve() 換回全文）"
        else:
            input_desc = f"text_input={c.text_input!r}"
        print(f"[{c.case_id}] category={c.category} call_target={c.call_target}")
        print(f"      purpose: {c.purpose}")
        print(f"      {input_desc}")
        print(f"      hard_checks: {c.hard_checks}\n")


def _print_summary(records: list[dict]) -> None:
    by_case: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_case[r["case_id"]].append(r)

    print("\n=== 摘要 ===")
    header = f"{'case_id':<6} {'runs':<5} {'skip':<5} {'err':<4} {'avg_latency_s':<14} {'avg_in_tok':<11} {'avg_out_tok':<12} {'hard_checks'}"
    print(header)
    print("-" * len(header))

    for case_id in sorted(by_case, key=lambda cid: list(by_case).index(cid)):
        recs = by_case[case_id]
        ok_recs = [r for r in recs if not r["skipped"] and not r["error"]]
        skipped = sum(1 for r in recs if r["skipped"])
        errored = sum(1 for r in recs if r["error"])

        latencies = [r["total_latency_s"] for r in ok_recs if r["total_latency_s"] is not None]
        in_toks = [r["total_input_tokens"] for r in ok_recs if r["total_input_tokens"] is not None]
        out_toks = [r["total_output_tokens"] for r in ok_recs if r["total_output_tokens"] is not None]

        avg_latency = f"{sum(latencies)/len(latencies):.2f}" if latencies else "-"
        avg_in = f"{sum(in_toks)/len(in_toks):.0f}" if in_toks else "-"
        avg_out = f"{sum(out_toks)/len(out_toks):.0f}" if out_toks else "-"

        check_summary = []
        check_names = set()
        for r in ok_recs:
            check_names.update(r["hard_check_results"].keys())
        for name in sorted(check_names):
            passed = sum(1 for r in ok_recs if r["hard_check_results"].get(name, {}).get("passed"))
            total = sum(1 for r in ok_recs if name in r["hard_check_results"])
            check_summary.append(f"{name}={passed}/{total}")

        print(f"{case_id:<6} {len(recs):<5} {skipped:<5} {errored:<4} {avg_latency:<14} {avg_in:<11} {avg_out:<12} {', '.join(check_summary)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Baseline eval harness（OpenAI Responses API pipeline）")
    parser.add_argument(
        "--cases", type=str, default=",".join(TEXT_CASE_IDS),
        help=f"逗號分隔的 case id（預設今天可跑的文字案例：{','.join(TEXT_CASE_IDS)}）",
    )
    parser.add_argument("--n", type=int, default=3, help="每個 case 重複跑幾次（預設 3）")
    parser.add_argument("--label", type=str, default=None, help="附加進檔名的標籤")
    parser.add_argument("--out", type=Path, default=None, help="覆寫預設輸出目錄")
    parser.add_argument("--dry-run", action="store_true", help="只列出會跑什麼，不呼叫任何真實 API")
    args = parser.parse_args()

    case_ids = [c.strip() for c in args.cases.split(",") if c.strip()]
    selected_cases = _resolve_selected_cases(case_ids)

    if args.dry_run:
        _print_dry_run(selected_cases)
        return

    out_dir = args.out or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    suffix = f"-{args.label}" if args.label else "-gpt-5.6-terra"
    jsonl_path = out_dir / f"baseline-{timestamp}{suffix}.jsonl"
    meta_path = out_dir / f"baseline-{timestamp}{suffix}.meta.json"

    print(f"開始執行 {len(selected_cases)} 個 case × {args.n} 次 = {len(selected_cases) * args.n} 次 case-run")
    print(f"（實際 API 呼叫次數會更多：每個 analyze_product_name_openai case 最多觸發 4 次 responses.create + 1 次 retrieve）\n")

    prior_results: dict = {}
    all_records: list[dict] = []

    for run_index in range(args.n):
        for case in selected_cases:
            print(f"  run {run_index + 1}/{args.n}  case {case.case_id} ...", end=" ", flush=True)
            record = harness.run_case_openai(case, run_index, prior_results)
            all_records.append(record)
            if record["skipped"]:
                print(f"SKIPPED（{record['skip_reason']}）")
            elif record["error"]:
                print(f"ERROR（{record['error']}）")
            else:
                print(f"ok（{record['total_latency_s']:.2f}s, "
                      f"{record['total_input_tokens']}/{record['total_output_tokens']} tok）")

    with jsonl_path.open("w", encoding="utf-8") as f:
        for record in all_records:
            f.write(json.dumps(harness.strip_internal_fields(record), ensure_ascii=False) + "\n")

    cases_run = [c.case_id for c in selected_cases if not any(
        r["case_id"] == c.case_id and r["skipped"] for r in all_records
    )]
    cases_skipped = sorted({r["case_id"] for r in all_records if r["skipped"]})

    meta = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "models_observed": harness.detect_models_used(all_records),
        "openai_sdk_version": harness.get_openai_sdk_version(),
        "git_commit": harness.get_git_commit(),
        "cases_fingerprint": harness.compute_cases_fingerprint(CASES),
        "cases_run": sorted({c.case_id for c in selected_cases}),
        "cases_skipped": cases_skipped,
        "n_runs": args.n,
        "pricing_note": (
            "estimated_cost_usd 目前一律為 null——PRICING_PER_MTOK_OPENAI 尚未填入官方即時價格，"
            "使用前請至 https://openai.com/api/pricing 確認，不要用記憶中的舊數字。"
        ),
    }
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"\n寫入：{jsonl_path}")
    print(f"寫入：{meta_path}")
    _print_summary(all_records)


if __name__ == "__main__":
    main()
