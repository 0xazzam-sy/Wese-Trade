"""Synthetic 10-minute candles built from 5-minute candles.

Buckets are aligned to UTC epoch boundaries (hh:00, hh:10, ..., hh:50) by flooring the
5m open time to a multiple of 600 s, never by pairing array positions.

    open = first child open      high = max(child highs)   low = min(child lows)
    close = last child close     volume / quote volume / trade count = sums

A 10m candle is CLOSED only when both 5m children exist, both are closed and the bucket
has ended. Historical buckets missing a child are dropped (a visible gap) rather than
fabricated. The current bucket is emitted as forming (is_closed=False).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe

TARGET = Timeframe.M10
SOURCE = Timeframe.M5
CHILDREN_PER_BUCKET = TARGET.seconds // SOURCE.seconds  # 2


def _sum_decimals(values: Iterable[Decimal | None]) -> Decimal | None:
    items = list(values)
    if any(v is None for v in items):
        return None
    return sum((v for v in items if v is not None), Decimal(0))


def _sum_ints(values: Iterable[int | None]) -> int | None:
    items = list(values)
    if any(v is None for v in items):
        return None
    return sum(v for v in items if v is not None)


def build_bucket(children: Sequence[Candle], *, now_ms: int) -> Candle:
    """Aggregate the given 5m children (any non-empty subset of one bucket)."""
    ordered = sorted(children, key=lambda c: c.open_ms)
    first = ordered[0]
    bucket_ms = TARGET.bucket_start_ms(first.open_ms)
    if any(TARGET.bucket_start_ms(c.open_ms) != bucket_ms for c in ordered):
        raise ValueError("children belong to different 10m buckets")
    complete = len(ordered) == CHILDREN_PER_BUCKET and all(c.is_closed for c in ordered)
    ended = bucket_ms + TARGET.milliseconds <= now_ms
    return Candle(
        symbol=first.symbol,
        timeframe=TARGET,
        open_time=first.open_time - timedelta(milliseconds=first.open_ms - bucket_ms),
        open=first.open,
        high=max(c.high for c in ordered),
        low=min(c.low for c in ordered),
        close=ordered[-1].close,
        volume=sum((c.volume for c in ordered), Decimal(0)),
        is_closed=complete and ended,
        quote_volume=_sum_decimals(c.quote_volume for c in ordered),
        trade_count=_sum_ints(c.trade_count for c in ordered),
    )


def aggregate_history(source: Sequence[Candle], *, now_ms: int) -> list[Candle]:
    """Aggregate chronological 5m history into 10m candles (see module docstring)."""
    buckets: dict[int, dict[int, Candle]] = {}
    for candle in source:
        if candle.timeframe is not SOURCE:
            raise ValueError("aggregate_history expects 5m candles")
        buckets.setdefault(TARGET.bucket_start_ms(candle.open_ms), {})[candle.open_ms] = candle

    current_bucket = TARGET.bucket_start_ms(now_ms)
    result: list[Candle] = []
    for bucket_ms in sorted(buckets):
        children = list(buckets[bucket_ms].values())
        candle = build_bucket(children, now_ms=now_ms)
        if candle.is_closed or bucket_ms >= current_bucket:
            result.append(candle)
        # else: past bucket with a missing/unfinished child -> excluded, never fabricated
    return result


@dataclass
class LiveAggregator:
    """Maintains the forming 10m candle for one symbol from live 5m updates."""

    symbol: str
    bucket_ms: int | None = None
    children: dict[int, Candle] = field(default_factory=dict)
    finalized: bool = False

    def seed(self, candles: Iterable[Candle], *, now_ms: int) -> None:
        """Load the current bucket's already-known children (e.g. from history)."""
        current = TARGET.bucket_start_ms(now_ms)
        self.bucket_ms = current
        self.children = {
            c.open_ms: c for c in candles if TARGET.bucket_start_ms(c.open_ms) == current
        }
        self.finalized = False

    def update(self, candle: Candle, *, now_ms: int) -> list[Candle]:
        """Apply one 5m update; return 10m candles to emit (in order)."""
        bucket = TARGET.bucket_start_ms(candle.open_ms)
        emitted: list[Candle] = []
        if self.bucket_ms is not None and bucket < self.bucket_ms:
            return emitted  # late update for an older bucket; REST reconciliation owns it
        if self.bucket_ms is not None and bucket > self.bucket_ms:
            emitted.extend(self._finalize_previous(now_ms=now_ms))
            self.bucket_ms, self.children, self.finalized = bucket, {}, False
        if self.bucket_ms is None:
            self.bucket_ms = bucket

        previous = self.children.get(candle.open_ms)
        if previous is not None and previous.same_values(candle):
            return emitted  # duplicate update
        self.children[candle.open_ms] = candle
        aggregated = build_bucket(list(self.children.values()), now_ms=now_ms)
        if aggregated.is_closed:
            if not self.finalized:
                self.finalized = True
                emitted.append(aggregated)
        else:
            emitted.append(aggregated)
        return emitted

    def _finalize_previous(self, *, now_ms: int) -> list[Candle]:
        if self.finalized or not self.children:
            return []
        # The bucket has rolled over: any child still flagged forming is final now.
        closed_children = [c.closed() for c in self.children.values()]
        aggregated = build_bucket(closed_children, now_ms=now_ms)
        self.finalized = True
        return [aggregated] if aggregated.is_closed else []
