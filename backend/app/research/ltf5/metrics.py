"""Trade statistics for LTF-5 research: expectancy, PF, drawdown, streaks, bootstrap CI."""

from __future__ import annotations

import random
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

from app.research.ltf5.sim import Trade

DAY_MS = 86_400_000


def _pf(rs: Sequence[float]) -> float | None:
    win = sum(r for r in rs if r > 0)
    loss = -sum(r for r in rs if r < 0)
    return round(win / loss, 3) if loss > 0 else None


def max_drawdown(trades: Sequence[Trade]) -> float:
    equity = peak = dd = 0.0
    for tr in sorted(trades, key=lambda x: x.exit_time):
        equity += tr.net_r
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return round(dd, 2)


def losing_streak(trades: Sequence[Trade]) -> int:
    best = cur = 0
    for tr in sorted(trades, key=lambda x: x.exit_time):
        cur = cur + 1 if tr.net_r < 0 else 0
        best = max(best, cur)
    return best


def bootstrap_ci(
    trades: Sequence[Trade], level: float = 0.90, draws: int = 2000, seed: int = 7
) -> tuple[float, float] | None:
    """Block bootstrap by calendar day of the mean net R (keeps intraday dependence)."""
    if len(trades) < 20:
        return None
    by_day: dict[int, list[float]] = defaultdict(list)
    for tr in trades:
        by_day[tr.exit_time // DAY_MS].append(tr.net_r)
    days = list(by_day.values())
    rng = random.Random(seed)  # noqa: S311 - reproducible statistics, not security
    means = []
    for _ in range(draws):
        total = count = 0.0
        for _ in range(len(days)):
            d = days[rng.randrange(len(days))]
            total += sum(d)
            count += len(d)
        means.append(total / count)
    means.sort()
    lo = means[int((1 - level) / 2 * draws)]
    hi = means[int((1 + level) / 2 * draws) - 1]
    return round(lo, 4), round(hi, 4)


def summary(
    trades: Sequence[Trade], span_days: float | None = None, ci: bool = False
) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    net = [t.net_r for t in trades]
    out: dict[str, Any] = {
        "trades": n,
        "win_rate": round(sum(r > 0 for r in net) / n, 3),
        "loss_rate": round(sum(r < 0 for r in net) / n, 3),
        "gross_e": round(statistics.fmean(t.gross_r for t in trades), 4),
        "after_fee_e": round(statistics.fmean(t.fee_r for t in trades), 4),
        "net_e": round(statistics.fmean(net), 4),
        "net_high_e": round(statistics.fmean(t.net_high_r for t in trades), 4),
        "median_r": round(statistics.median(net), 4),
        "pf": _pf(net),
        "total_r": round(sum(net), 2),
        "max_dd": max_drawdown(trades),
        "max_losing_streak": losing_streak(trades),
        "avg_bars": round(statistics.fmean(t.bars for t in trades), 1),
        "fees_r": round(statistics.fmean(t.gross_r - t.fee_r for t in trades), 4),
        "slippage_r": round(statistics.fmean(t.fee_r - t.net_r for t in trades), 4),
        "avg_risk_pct": round(statistics.fmean(t.risk_pct for t in trades), 3),
        "long": sum(t.side == 1 for t in trades),
        "short": sum(t.side == -1 for t in trades),
    }
    if span_days:
        out["per_day"] = round(n / span_days, 2)
        out["per_week"] = round(7 * n / span_days, 1)
    if ci:
        out["ci90"] = bootstrap_ci(trades)
    return out


def group(
    trades: Sequence[Trade], key: Callable[[Trade], object], min_n: int = 1
) -> dict[str, dict[str, Any]]:
    buckets: dict[object, list[Trade]] = defaultdict(list)
    for tr in trades:
        buckets[key(tr)].append(tr)
    return {
        str(k): summary(v) | ({"warning": "INSUFFICIENT_SAMPLE"} if len(v) < min_n else {})
        for k, v in sorted(buckets.items(), key=lambda kv: str(kv[0]))
    }


def session(hour: int) -> str:
    """UTC liquidity sessions (overlaps reported separately)."""
    if 13 <= hour < 16:
        return "london_ny_overlap"
    if 7 <= hour < 13:
        return "london"
    if 16 <= hour < 21:
        return "new_york"
    return "asia"


def regime(t: Trade) -> str:
    """Deterministic regime label at signal time (context strength + volatility)."""
    vol = "vol_high" if t.atr_pct >= 80 else "vol_low" if t.atr_pct <= 20 else "vol_mid"
    trend = "trending" if t.ctx_strength >= 1.0 else "weak_trend" if t.ctx_dir else "range"
    return f"{trend}/{vol}"
