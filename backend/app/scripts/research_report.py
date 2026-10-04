# ruff: noqa: E501, RUF001  (Markdown table rendering: long literal rows are clearer unwrapped)
"""Render a research report JSON (data/research/reports/<name>.json) as Markdown tables.

python -m app.scripts.research_report --name phase41 > /tmp/phase41.md
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from app.research.store import RESEARCH_DIR


def f(v: Any, d: int = 3, sign: bool = True) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:+.{d}f}" if sign else f"{v:.{d}f}"
    return str(v)


def day(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def row(name: str, s: dict[str, Any]) -> str:
    flag = "" if s.get("sample", "OK") == "OK" else " ⚠"
    return (
        f"| {name} | {s['entered']}{flag} | {f(s['win_rate'] * 100 if s['win_rate'] is not None else None, 1, False)}% "
        f"| {f(s['gross_expectancy'])} | {f(s['expectancy'])} | {f(s['profit_factor'], 2, False)} "
        f"| {f(s['max_drawdown_r'], 1, False)} |"
    )


HEAD = "| Group | Trades | Win | Gross E[R] | Net E[R] | PF | Max DD (R) |\n|---|---:|---:|---:|---:|---:|---:|"


def table(title: str, groups: dict[str, dict[str, Any]]) -> str:
    lines = [f"**{title}**", "", HEAD]
    lines += [row(k, v) for k, v in groups.items()]
    return "\n".join(lines) + "\n"


def summary_block(name: str, s: dict[str, Any]) -> str:
    w = s["windows"]
    a = s["assessment"]
    lines = [
        f"### {name}",
        "",
        f"`{s.get('version', '')}` — assessment: **{a['status']}**"
        + ("" if not a["reasons"] else f" ({'; '.join(a['reasons'])})"),
        "",
        HEAD,
        row("pre-period (development)", s["pre_period"]),
        *(row(k, v) for k, v in w.items()),
        row("**validation W1–W3**", s["validation"]),
        row("validation, fresh symbols", s["fresh_validation"]),
        row("validation, anchors (contaminated)", s["anchor_validation"]),
        "",
    ]
    for key in ("by_timeframe", "by_symbol", "by_family", "by_regime", "by_side"):
        if key in s:
            lines.append(table(f"{name} — validation {key[3:]}", s[key]))
    if "calibration" in s:
        lines += [
            f"**{name} — score calibration (validation)**",
            "",
            "| Score | Trades | Win | E[R] | PF |",
            "|---|---:|---:|---:|---:|",
        ]
        for c in s["calibration"]:
            if c["n"]:
                flag = "" if c["sample"] == "OK" else " ⚠"
                win = None if c["win"] is None else c["win"] * 100
                lines.append(
                    f"| {c['bucket']} | {c['n']}{flag} | {f(win, 1, False)}% | {f(c['exp'])} | {f(c['pf'], 2, False)} |"
                )
        lines.append("")
    return "\n".join(lines)


def brief_table(title: str, rows: dict[str, dict[str, Any]]) -> str:
    out = [
        f"**{title}**",
        "",
        "| Variant | Val n | Val E[R] | Val PF | W1 | W2 | W3 | Fresh n / E[R] | Status |",
        "|---|---:|---:|---:|---|---|---|---|---|",
    ]
    for name, b in rows.items():
        ws = " | ".join(f"{n} / {f(e)}" for n, e, _ in b["windows"].values())
        out.append(
            f"| {name} | {b['val_n']} | {f(b['val_exp'])} | {f(b['val_pf'], 2, False)} | {ws} "
            f"| {b['fresh'][0]} / {f(b['fresh'][1])} | {b['assessment']['status']} |"
        )
    return "\n".join(out) + "\n"


def main(name: str) -> None:
    r = json.loads((RESEARCH_DIR / "reports" / f"{name}.json").read_text())
    print(f"# Research report `{name}`\n")
    print(f"Baseline `{r['baseline_version']}`, analysis `{r['analysis_version']}`.\n")
    print(
        "Windows: "
        + ", ".join(f"{w['name']} {day(w['start'])}→{day(w['end'])}" for w in r["windows"])
        + "\n"
    )
    print("## Coverage\n\n| Series | Candles | Days | Gaps |\n|---|---:|---:|---:|")
    for k, c in r["coverage"].items():
        print(
            f"| {k} | {c['candles']} | {((c['last_ms'] or 0) - (c['first_ms'] or 0)) / 86_400_000:.0f} | {c['gaps']} |"
        )
    print("\n## Cost efficiency\n")
    print(
        "| TF | Median ATR % | Cost R @1ATR stop | Plans rejected by cost floor | Median plan risk % | Median realized cost R | Verdict |"
    )
    print("|---|---:|---:|---:|---:|---:|---|")
    for tf, c in r["cost_efficiency"]["by_timeframe"].items():
        print(
            f"| {tf} | {f(c['median_atr_pct'], 3, False)} | {f(c['cost_r_if_stop_1atr'], 2, False)} "
            f"| {f(c['plans_rejected_cost_floor_pct'], 1, False)}% | {f(c['median_plan_risk_pct'], 2, False)} "
            f"| {f(c['median_realized_cost_r'], 3, False)} | {c['verdict']} |"
        )
    for study, variants in r["studies"].items():
        print(f"\n## Study: {study}\n")
        for vname, s in variants.items():
            if study in ("baseline", "families", "regimes", "score"):
                print(summary_block(vname, s))
        print(brief_table(f"{study} — summary", {k: _brief(v) for k, v in variants.items()}))
    print("\n## 1m / 10m (baseline, research-only)\n")
    print(brief_table("1m/10m", {k: _brief(v) for k, v in r["baseline_1m_10m"].items()}))
    print("\n## LTF execution\n")
    for base, block in r["ltf"].items():
        for tf, b in block.items():
            print(f"**{base} {tf}** counts: {b['counts']} pullback: {b.get('pullback_counts')}\n")
            print(HEAD)
            print(row("native HTF bars", b["native_htf_bars"]))
            print(row("A5 market at confirmation (5m path)", b["A5_market_at_confirmation"]))
            print(row("D5 5m CHoCH entry", b["D5_5m_choch_entry"]))
            print(row("D5b pullback then 5m BOS/CHoCH", b["D5b_pullback_then_5m_event"]))
            print()
    print("\n## Score components\n")
    print(
        "| Component | n (pre) | Spearman pre | 2SE | W1 | W2 | W3 | pre anchor | pre fresh | Q1→Q5 E[R] (pre) |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for k, v in r["score_components"].items():
        if k.startswith("_"):
            continue
        st = v["stability"]
        qs = " / ".join(f(q["exp"]) for q in v["quintiles_pre"])
        print(
            f"| {k} | {v['n_pre']} | {f(v['spearman_pre'])} | {f(v['significance_2se'], 3, False)} | {f(st.get('W1'))} "
            f"| {f(st.get('W2'))} | {f(st.get('W3'))} | {f(st.get('pre_anchor'))} | {f(st.get('pre_fresh'))} | {qs} |"
        )
    print("\nBaseline score (pre):", r["score_components"]["_baseline_score_pre"]["spearman"])
    print(
        "\nPenalties (pre):\n\n| Code | n with | E[R] with | E[R] without |\n|---|---:|---:|---:|"
    )
    for k, v in r["score_components"]["_penalties_pre"].items():
        print(f"| {k} | {v['n_with']} | {f(v['exp_with'])} | {f(v['exp_without'])} |")
    print("\nDerived score model:", r["score_model_s41"])
    print("\n## Correlations (pre)\n")
    cols = list(r["correlations"])
    print("| | " + " | ".join(cols) + " |\n|---|" + "---:|" * len(cols))
    for a in cols:
        print(f"| {a} | " + " | ".join(f(r["correlations"][a][b], 2) for b in cols) + " |")
    print("\n## Interactions\n")
    for k, cells in r["interactions"].items():
        print(
            f"**{k}**: "
            + "; ".join(f"{c} n={v['n']} E={f(v['exp'])}" for c, v in cells.items())
            + "\n"
        )
    print("\n## Funding\n")
    print(json.dumps(r["funding"], indent=1))
    print("\n## Reversal diagnostics\n")
    print(json.dumps(r["reversal_diagnostics"], indent=1))
    print("\n## Candidates\n")
    for scope, block in r["candidates"].items():
        print(brief_table(f"scope {scope}", block["grid"]))
        sel = block["walk_forward_selection"]
        print(f"**Walk-forward selection ({scope})**\n")
        for w in sel["per_window"]:
            print(f"- {w}")
        print(f"- out-of-sample selected: {row('selected', sel['out_of_sample_selected'])}")
        print(f"- fresh only: {row('fresh', sel['fresh_only'])}\n")
    print("\nPassing candidates:", r["passing_candidates"])
    for k, s in r.get("robustness", {}).items():
        print(summary_block(f"robustness {k}", s))
    print(f"\nElapsed: {r['elapsed_s']}s")


def _brief(s: dict[str, Any]) -> dict[str, Any]:
    v = s["validation"]
    return {
        "val_n": v["entered"],
        "val_exp": v["expectancy"],
        "val_pf": v["profit_factor"],
        "windows": {
            k: (w["entered"], w["expectancy"], w["profit_factor"]) for k, w in s["windows"].items()
        },
        "fresh": (s["fresh_validation"]["entered"], s["fresh_validation"]["expectancy"]),
        "assessment": s["assessment"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="phase41")
    main(parser.parse_args().name)
