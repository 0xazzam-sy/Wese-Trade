"""Volume features. Uses BASE-currency candle volume (OKX `volCcy`) consistently.

OKX candles carry no buy/sell split, so no buy/sell volume is ever inferred."""

from __future__ import annotations

from collections.abc import Sequence

from app.analysis.indicators.stats import mean, percentile_rank, stdev
from app.analysis.models import VolumeFeatures


def relative_volume(previous: Sequence[float], current: float) -> float | None:
    if not previous:
        return None
    avg = mean(previous)
    return current / avg if avg > 0 else None


def volume_features(
    previous: Sequence[float],
    current: float,
    percentile_window: Sequence[float],
    *,
    spike_ratio: float,
    contraction_ratio: float,
) -> VolumeFeatures:
    """`previous`: the lookback volumes BEFORE the current candle (current is excluded)."""
    if not previous:
        return VolumeFeatures(current, None, None, None, None, False, False)
    avg = mean(previous)
    sd = stdev(previous)
    rel = current / avg if avg > 0 else None
    z = (current - avg) / sd if sd > 0 else None
    pct = percentile_rank(percentile_window, current) if percentile_window else None
    return VolumeFeatures(
        volume=current,
        average=avg,
        relative=rel,
        zscore=z,
        percentile=pct,
        spike=rel is not None and rel >= spike_ratio,
        contraction=rel is not None and rel <= contraction_ratio,
    )
