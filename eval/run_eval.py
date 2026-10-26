"""Evaluate the reviewer on the seeded-bug set.

Modes (each reports precision / recall / F1 per category, FP rate on clean PRs, latency):
  static    ruff + bandit only (real tools, real numbers)
  scripted  specialist agents driven by hand-authored responses, no static evidence
  combined  scripted agents + static evidence/findings, deduped by the aggregator
  llm       same as combined but with the real Anthropic model (needs ANTHROPIC_API_KEY)

A finding matches an expected issue when file and category agree and lines are within
2 of each other. Unmatched findings are false positives; unmatched issues are misses.

  python -m eval.run_eval [--modes static,scripted,combined] [--out eval/results/latest.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from pathlib import Path

from reviewer.llm import FakeLLM, tool_use
from reviewer.orchestrator import review_diff
from reviewer.schemas import Category
from reviewer.sources import DictSource, LocalSource

from .cases import CASES, Case

LINE_TOL = 2
CATS = [c.value for c in Category]


def make_fake_llm(case: Case, expected: list[dict], first_added: int) -> FakeLLM:
    def line_for(s) -> int:
        if s.line is not None:
            return s.line
        if s.marker is None:
            return first_added
        return expected[s.marker]["line"]

    def script(agent: str, turn: int, _messages):
        if turn == 0:
            return [tool_use("t1", "get_static_findings")]
        if turn == 1:
            findings = [
                {
                    "file": s.file or case.path,
                    "line": line_for(s),
                    "severity": s.severity,
                    "category": s.category,
                    "message": s.message,
                    **({"suggestion": s.suggestion} if s.suggestion else {}),
                }
                for s in case.script
                if s.category == agent
            ]
            return [tool_use("t2", "submit_findings", findings=findings)]
        return None

    return FakeLLM(script)


def match(findings, expected):
    """Greedy one-to-one matching. Returns (tp pairs, fp findings, fn expected)."""
    used: set[int] = set()
    tps, fns = [], []
    for e in expected:
        hit = next(
            (
                i for i, f in enumerate(findings)
                if i not in used and f.file == e["file"] and f.category.value == e["category"]
                and abs(f.line - e["line"]) <= LINE_TOL
            ),
            None,
        )
        if hit is None:
            fns.append(e)
        else:
            used.add(hit)
            tps.append((findings[hit], e))
    fps = [f for i, f in enumerate(findings) if i not in used]
    return tps, fps, fns


async def run_mode(mode: str) -> dict:
    per_cat = {c: {"tp": 0, "fp": 0, "fn": 0} for c in CATS}
    clean_total = clean_with_fp = 0
    latencies, dropped_out, dropped_inv, merged = [], 0, 0, 0
    in_tok = out_tok = 0
    for case in CASES:
        diff, files, expected = case.build()
        first_added = case.first_added_line
        t0 = time.perf_counter()
        with tempfile.TemporaryDirectory() as tmp:
            for p, text in files.items():
                (Path(tmp) / p).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / p).write_text(text, encoding="utf-8")
            src = LocalSource(Path(tmp))
            if mode == "static":
                res = await review_diff(diff, src, None)
            elif mode == "scripted":
                res = await review_diff(
                    diff, DictSource(files), make_fake_llm(case, expected, first_added),
                    use_static=False,
                )
            elif mode == "combined":
                res = await review_diff(diff, src, make_fake_llm(case, expected, first_added))
            elif mode == "llm":
                from reviewer.llm import AnthropicLLM

                res = await review_diff(diff, src, AnthropicLLM())
            else:
                raise SystemExit(f"unknown mode {mode}")
        latencies.append(time.perf_counter() - t0)
        dropped_out += res.dropped_out_of_diff
        dropped_inv += res.dropped_invalid
        merged += res.merged_duplicates
        in_tok += res.input_tokens
        out_tok += res.output_tokens
        tps, fps, fns = match(res.findings, expected)
        for _, e in tps:
            per_cat[e["category"]]["tp"] += 1
        for f in fps:
            per_cat[f.category.value]["fp"] += 1
        for e in fns:
            per_cat[e["category"]]["fn"] += 1
        if not expected:
            clean_total += 1
            clean_with_fp += bool(res.findings)

    def prf(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return p, r, (2 * p * r / (p + r) if p + r else 0.0)

    cats = {}
    for c, v in per_cat.items():
        p, r, f1 = prf(**v)
        cats[c] = {**v, "precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3)}
    tot = {k: sum(v[k] for v in per_cat.values()) for k in ("tp", "fp", "fn")}
    p, r, f1 = prf(**tot)
    return {
        "mode": mode,
        "overall": {**tot, "precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3)},
        "per_category": cats,
        "clean_prs": clean_total,
        "clean_prs_with_false_positive": clean_with_fp,
        "false_positive_rate_on_clean_prs": round(clean_with_fp / clean_total, 3),
        "dropped_out_of_diff": dropped_out,
        "dropped_invalid": dropped_inv,
        "merged_duplicates": merged,
        "latency_ms_mean": round(statistics.mean(latencies) * 1000, 1),
        "latency_ms_p95": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))] * 1000, 1),
        "tokens": {"input": in_tok, "output": out_tok},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="static,scripted,combined")
    ap.add_argument("--out", default="eval/results/latest.json")
    args = ap.parse_args()
    results = [asyncio.run(run_mode(m)) for m in args.modes.split(",")]
    n_issues = sum(len(c.build()[2]) for c in CASES)
    out = {"cases": len(CASES), "labelled_issues": n_issues, "results": results}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"{len(CASES)} cases, {n_issues} labelled issues\n")
    hdr = f"{'mode':<10}{'P':>7}{'R':>7}{'F1':>7}{'TP':>5}{'FP':>5}{'FN':>5}{'cleanFP':>9}{'ms/PR':>9}"
    print(hdr)
    for r in results:
        o = r["overall"]
        print(
            f"{r['mode']:<10}{o['precision']:>7}{o['recall']:>7}{o['f1']:>7}{o['tp']:>5}{o['fp']:>5}"
            f"{o['fn']:>5}{r['false_positive_rate_on_clean_prs']:>9}{r['latency_ms_mean']:>9}"
        )
    for r in results:
        print(f"\n[{r['mode']}] per category")
        for c, v in r["per_category"].items():
            print(f"  {c:<12} P={v['precision']} R={v['recall']} F1={v['f1']} (tp={v['tp']} fp={v['fp']} fn={v['fn']})")


if __name__ == "__main__":
    main()
