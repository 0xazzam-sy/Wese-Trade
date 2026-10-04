"""Streaming indicator state: updated once per CLOSED candle, never rewound."""

from __future__ import annotations

import math
from collections import deque
from itertools import pairwise

from app.analysis.config import AnalysisConfig
from app.analysis.enums import EmaStack, SpreadState, TrendDirection, VolatilityRegime
from app.analysis.indicators.atr import Atr
from app.analysis.indicators.ema import Ema
from app.analysis.indicators.momentum import acceleration, impulse_atr, roc
from app.analysis.indicators.rsi import Rsi
from app.analysis.indicators.stats import clamp, percentile_rank, stdev
from app.analysis.indicators.volume import volume_features
from app.analysis.models import (
    EmaFeature,
    MomentumFeatures,
    TrendFeatures,
    VolatilityFeatures,
    VolumeFeatures,
)
from app.analysis.series import Bar


class IndicatorState:
    def __init__(self, config: AnalysisConfig) -> None:
        self.config = config
        keep = (
            max(
                config.atr_percentile_window,
                config.volume_percentile_window,
                config.range_compression_long,
                2 * max(config.roc_period, config.accel_period),
                config.efficiency_window,
                config.realized_vol_window,
                config.volume_lookback,
                config.rsi_slope_lookback,
            )
            + 5
        )
        self.emas = {p: Ema(p) for p in config.ema_periods}
        self.atr = Atr(config.atr_period)
        self.rsi = Rsi(config.rsi_period)
        self.closes: deque[float] = deque(maxlen=keep)
        self.highs: deque[float] = deque(maxlen=keep)
        self.lows: deque[float] = deque(maxlen=keep)
        self.volumes: deque[float] = deque(maxlen=keep)
        self.ema_hist: dict[int, deque[float | None]] = {
            p: deque(maxlen=config.ema_slope_lookback + 1) for p in config.ema_periods
        }
        self.atr_hist: deque[float | None] = deque(maxlen=keep)
        self.atr_pct_hist: deque[float] = deque(maxlen=config.atr_percentile_window)
        self.rsi_hist: deque[float | None] = deque(maxlen=keep)
        self.spread_hist: deque[float | None] = deque(maxlen=config.ema_spread_lookback + 1)
        self.rsi_by_index: dict[int, float] = {}  # for divergence hooks (bounded below)

    # --- update -------------------------------------------------------------------
    def update(self, bar: Bar) -> None:
        self.closes.append(bar.close)
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.volumes.append(bar.volume)
        for period, ema in self.emas.items():
            self.ema_hist[period].append(ema.update(bar.close))
        atr = self.atr.update(bar.high, bar.low, bar.close)
        self.atr_hist.append(atr)
        if atr is not None and bar.close > 0:
            self.atr_pct_hist.append(atr / bar.close * 100)
        rsi = self.rsi.update(bar.close)
        self.rsi_hist.append(rsi)
        if rsi is not None:
            self.rsi_by_index[bar.index] = rsi
            if len(self.rsi_by_index) > 1200:
                for key in sorted(self.rsi_by_index)[:200]:
                    del self.rsi_by_index[key]
        self.spread_hist.append(self._spread())

    def _spread(self) -> float | None:
        fast, slow = self.config.ema_periods[0], self.config.ema_periods[-1]
        f, s, a = self.emas[fast].value, self.emas[slow].value, self.atr.value
        if f is None or s is None or not a:
            return None
        return (f - s) / a

    # --- accessors ------------------------------------------------------------------
    @property
    def atr_value(self) -> float | None:
        return self.atr.value

    @property
    def prev_atr(self) -> float | None:
        """ATR before the latest bar (so a candle is never measured against itself)."""
        return self.atr_hist[-2] if len(self.atr_hist) >= 2 else None

    def relative_volume_at_last(self) -> float | None:
        lookback = self.config.volume_lookback
        if len(self.volumes) < lookback + 1:
            return None
        prev = list(self.volumes)[-lookback - 1 : -1]
        avg = sum(prev) / len(prev)
        return self.volumes[-1] / avg if avg > 0 else None

    @property
    def ready(self) -> bool:
        return all(e.value is not None for e in self.emas.values()) and bool(self.atr.value)

    # --- features ------------------------------------------------------------------------
    def trend(self) -> TrendFeatures | None:
        if not self.ready:
            return None
        cfg = self.config
        atr = self.atr.value or 0.0
        close = self.closes[-1]
        emas: list[EmaFeature] = []
        for period in cfg.ema_periods:
            hist = self.ema_hist[period]
            value = hist[-1]
            if value is None:
                return None
            then = hist[0] if len(hist) == hist.maxlen else None
            slope = (value - then) / cfg.ema_slope_lookback if then is not None else 0.0
            emas.append(
                EmaFeature(
                    period=period,
                    value=value,
                    slope=slope,
                    normalized_slope=slope / atr if atr else None,
                    distance_atr=(close - value) / atr if atr else None,
                )
            )
        values = [e.value for e in emas]
        alignment = sum((1 if a > b else -1 if a < b else 0) for a, b in pairwise(values))
        pairs = len(values) - 1
        stack = (
            EmaStack.BULLISH
            if alignment == pairs
            else EmaStack.BEARISH
            if alignment == -pairs
            else EmaStack.MIXED
        )
        mid = emas[1] if len(emas) > 1 else emas[0]
        slope_score = clamp((mid.normalized_slope or 0.0) / cfg.trend_slope_full_scale)
        position_score = clamp((mid.distance_atr or 0.0) / 2.0)
        score = 0.4 * (alignment / pairs) + 0.4 * slope_score + 0.2 * position_score
        # EMA ordering alone is never enough: the EMA50 slope must agree with the score.
        mid_slope = mid.normalized_slope or 0.0
        if score >= cfg.trend_threshold and mid_slope >= cfg.trend_min_slope:
            direction = TrendDirection.BULLISH
        elif score <= -cfg.trend_threshold and mid_slope <= -cfg.trend_min_slope:
            direction = TrendDirection.BEARISH
        else:
            direction = TrendDirection.NEUTRAL
        spread = self.spread_hist[-1]
        then_spread = (
            self.spread_hist[0] if len(self.spread_hist) == self.spread_hist.maxlen else None
        )
        change = (
            abs(spread) - abs(then_spread)
            if spread is not None and then_spread is not None
            else None
        )
        state = SpreadState.FLAT
        if change is not None and change >= cfg.ema_spread_flat_atr:
            state = SpreadState.EXPANDING
        elif change is not None and change <= -cfg.ema_spread_flat_atr:
            state = SpreadState.COMPRESSING
        return TrendFeatures(
            direction=direction,
            score=score,
            emas=tuple(emas),
            stack=stack,
            alignment_score=alignment,
            spread_atr=spread,
            spread_change_atr=change,
            spread_state=state,
            price_above_ema200=close > emas[-1].value,
        )

    def volatility(self) -> VolatilityFeatures | None:
        atr = self.atr.value
        if not atr or not self.closes:
            return None
        cfg = self.config
        close = self.closes[-1]
        atr_pct = atr / close * 100 if close else 0.0
        window = list(self.atr_pct_hist)
        percentile = (
            percentile_rank(window[:-1], atr_pct)
            if len(window) >= cfg.atr_percentile_window // 2
            else None
        )
        rng = self.highs[-1] - self.lows[-1]
        prev = self.prev_atr
        realized = None
        n = cfg.realized_vol_window
        if len(self.closes) > n:
            closes = list(self.closes)[-n - 1 :]
            rets = [math.log(b / a) for a, b in pairwise(closes) if a > 0 and b > 0]
            realized = stdev(rets) * 100 if rets else None
        return VolatilityFeatures(
            atr=atr,
            atr_pct=atr_pct,
            atr_percentile=percentile,
            range_atr=rng / prev if prev else None,
            realized_vol=realized,
            regime=self.volatility_regime(percentile),
        )

    def volatility_regime(self, percentile: float | None) -> VolatilityRegime:
        cfg = self.config
        if percentile is None:
            return VolatilityRegime.NORMAL
        if percentile >= cfg.vol_extreme_percentile:
            return VolatilityRegime.EXTREME
        if percentile >= cfg.vol_high_percentile:
            return VolatilityRegime.HIGH
        if percentile < cfg.vol_low_percentile:
            return VolatilityRegime.LOW
        return VolatilityRegime.NORMAL

    def momentum(self, divergence: str | None) -> MomentumFeatures:
        cfg = self.config
        closes = list(self.closes)
        rsi = self.rsi.value
        rsi_vals = list(self.rsi_hist)
        slope = None
        k = cfg.rsi_slope_lookback
        if rsi is not None and len(rsi_vals) > k and rsi_vals[-1 - k] is not None:
            slope = (rsi - rsi_vals[-1 - k]) / k  # type: ignore[operator]
        cross = None
        prev = rsi_vals[-2] if len(rsi_vals) >= 2 else None
        if prev is not None and rsi is not None:
            if prev < 50 <= rsi:
                cross = "up"
            elif prev > 50 >= rsi:
                cross = "down"
        return MomentumFeatures(
            rsi=rsi,
            rsi_slope=slope,
            rsi_cross_50=cross,
            rsi_overbought=rsi is not None and rsi >= cfg.rsi_overbought,
            rsi_oversold=rsi is not None and rsi <= cfg.rsi_oversold,
            roc=roc(closes, cfg.roc_period),
            impulse_atr=impulse_atr(closes, cfg.roc_period, self.atr.value),
            acceleration=acceleration(closes, cfg.accel_period),
            divergence=divergence,
        )

    def volume(self) -> VolumeFeatures | None:
        if not self.volumes:
            return None
        cfg = self.config
        vols = list(self.volumes)
        previous = vols[-cfg.volume_lookback - 1 : -1]
        window = vols[-cfg.volume_percentile_window - 1 : -1]
        return volume_features(
            previous,
            vols[-1],
            window,
            spike_ratio=cfg.volume_spike_ratio,
            contraction_ratio=cfg.volume_contraction_ratio,
        )

    def efficiency_ratio(self) -> float | None:
        n = self.config.efficiency_window
        if len(self.closes) <= n:
            return None
        closes = list(self.closes)[-n - 1 :]
        path = sum(abs(b - a) for a, b in pairwise(closes))
        return abs(closes[-1] - closes[0]) / path if path > 0 else 0.0

    def range_compression(self) -> float | None:
        """Range of the last `short` bars / range of the last `long` bars (0-1)."""
        cfg = self.config
        if len(self.highs) < cfg.range_compression_long:
            return None
        highs, lows = list(self.highs), list(self.lows)
        short = max(highs[-cfg.range_compression_short :]) - min(
            lows[-cfg.range_compression_short :]
        )
        long = max(highs[-cfg.range_compression_long :]) - min(lows[-cfg.range_compression_long :])
        return short / long if long > 0 else None
