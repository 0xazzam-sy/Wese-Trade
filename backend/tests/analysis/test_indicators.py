from __future__ import annotations

import math

import pytest

from app.analysis.config import DEFAULT_CONFIG
from app.analysis.enums import EmaStack, FeatureStatus, SpreadState, TrendDirection
from app.analysis.indicators.atr import Atr, true_range
from app.analysis.indicators.candles import candle_features
from app.analysis.indicators.ema import Ema, ema_series
from app.analysis.indicators.momentum import acceleration, impulse_atr, roc
from app.analysis.indicators.rsi import Rsi
from app.analysis.indicators.state import IndicatorState
from app.analysis.indicators.stats import percentile_rank
from app.analysis.indicators.volume import relative_volume, volume_features
from app.analysis.series import to_bar
from tests.analysis.helpers import SMALL, candle, path


def test_ema_seeds_with_sma_then_smooths() -> None:
    values = ema_series([1, 2, 3, 4, 5], 3)
    assert values[:2] == [None, None]
    assert values[2] == pytest.approx(2.0)  # SMA(1,2,3)
    assert values[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)  # alpha = 2/(3+1)
    assert values[4] == pytest.approx(0.5 * 5 + 0.5 * 3.0)


def test_ema_peek_does_not_mutate() -> None:
    ema = Ema(3)
    for v in (1, 2, 3):
        ema.update(v)
    before = ema.value
    assert ema.peek(10) == pytest.approx(0.5 * 10 + 0.5 * 2.0)
    assert ema.value == before


def test_atr_wilder() -> None:
    assert true_range(10, 8, None) == 2
    assert true_range(10, 8, 12) == 4  # gap down: |low - prev close|
    atr = Atr(3)
    bars = [(10, 8, 9), (11, 9, 10), (12, 10, 11), (14, 10, 13)]
    out = [atr.update(h, lo, c) for h, lo, c in bars]
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx((2 + 2 + 2) / 3)
    assert out[3] == pytest.approx((2.0 * 2 + 4) / 3)


def test_rsi_extremes_and_peek() -> None:
    up = Rsi(3)
    for v in (1, 2, 3, 4, 5):
        up.update(v)
    assert up.value == 100.0
    flat = Rsi(3)
    for v in (5, 5, 5, 5):
        flat.update(v)
    assert flat.value == 50.0
    mixed = Rsi(2)
    for v in (10, 11, 10):
        mixed.update(v)
    assert mixed.value == pytest.approx(50.0)
    before = mixed.value
    assert mixed.peek(12) is not None and mixed.peek(12) > 50  # type: ignore[operator]
    assert mixed.value == before


def test_momentum_features() -> None:
    closes = [100, 101, 102, 104, 108, 116]
    assert roc(closes, 2) == pytest.approx((116 / 104 - 1) * 100)
    assert roc(closes, 10) is None
    assert impulse_atr(closes, 2, 4.0) == pytest.approx(3.0)
    assert acceleration(closes, 2) == pytest.approx((116 / 104 - 1) * 100 - (104 / 101 - 1) * 100)


def test_volume_features_relative_zscore_spike_contraction() -> None:
    prev = [10.0, 10.0, 10.0, 10.0]
    assert relative_volume(prev, 25) == 2.5
    spike = volume_features(prev, 25, prev, spike_ratio=2.0, contraction_ratio=0.5)
    assert spike.relative == 2.5 and spike.spike and not spike.contraction
    assert spike.zscore is None  # zero dispersion
    assert spike.percentile == 100.0
    quiet = volume_features([8.0, 12.0], 4, [8.0, 12.0], spike_ratio=2.0, contraction_ratio=0.5)
    assert quiet.contraction and quiet.zscore == pytest.approx((4 - 10) / 2)


def test_percentile_rank_ties_count_half() -> None:
    assert percentile_rank([1, 2, 3, 4], 2.5) == 50.0
    assert percentile_rank([1, 2, 2, 4], 2) == pytest.approx(50.0)


def test_candle_patterns_and_raw_features() -> None:
    prev = to_bar(candle(0, 10, 10.5, 8.8, 9), 0)
    engulf = to_bar(candle(1, 8.9, 11.2, 8.8, 11), 1)
    f = candle_features(engulf, prev, 1.0, FeatureStatus.CONFIRMED)
    assert "bullish_engulfing" in f.patterns and "strong_body" in f.patterns
    assert f.body_pct == pytest.approx(2.1 / 2.4)
    assert f.close_location == pytest.approx((11 - 8.8) / 2.4)
    pin = to_bar(candle(2, 10, 10.2, 7, 10.1), 2)
    assert "bullish_pin" in candle_features(pin, None, 1.0, FeatureStatus.CONFIRMED).patterns
    inside = to_bar(candle(3, 10, 10.4, 9.9, 10.1), 3)
    assert "inside_bar" in candle_features(inside, prev, 1.0, FeatureStatus.CONFIRMED).patterns


def test_trend_features_bullish_stack_and_spread() -> None:
    state = IndicatorState(SMALL)
    for i, c in enumerate(path([100 + i * 1.0 for i in range(30)])):
        state.update(to_bar(c, i))
    trend = state.trend()
    assert trend is not None
    assert trend.stack is EmaStack.BULLISH and trend.alignment_score == 3
    assert trend.direction is TrendDirection.BULLISH and trend.score > 0.6
    assert all(e.slope > 0 for e in trend.emas)
    assert trend.price_above_ema200 is True
    assert trend.spread_state in (SpreadState.FLAT, SpreadState.EXPANDING)
    vol = state.volatility()
    assert vol is not None and vol.atr > 0 and 0 <= (vol.atr_percentile or 0) <= 100
    assert vol.realized_vol is not None and not math.isnan(vol.realized_vol)
    momentum = state.momentum(None)
    assert momentum.rsi == 100.0 and momentum.rsi_overbought  # a feature flag, not a signal
    assert momentum.roc is not None and momentum.roc > 0


def test_trend_bearish_and_neutral() -> None:
    down = IndicatorState(SMALL)
    for i, c in enumerate(path([200 - i * 1.0 for i in range(30)])):
        down.update(to_bar(c, i))
    assert down.trend() is not None and down.trend().direction is TrendDirection.BEARISH  # type: ignore[union-attr]
    flat = IndicatorState(DEFAULT_CONFIG)
    sideways = [100 + 2 * math.sin(i / 7) for i in range(400)]
    for i, c in enumerate(path(sideways)):
        flat.update(to_bar(c, i))
    trend = flat.trend()
    assert trend is not None and trend.direction is TrendDirection.NEUTRAL
