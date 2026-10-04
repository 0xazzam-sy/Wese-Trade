"""Reference-counted market subscriptions.

App-level keys are what consumers (browser connections today, the scanner later) ask for:
(symbol, timeframe). Each maps to ONE native exchange stream (10m -> 5m). Exchange streams
are opened when their first dependent key appears and closed when the last one goes away,
so two charts on BTCUSDT 5m and 10m share a single exchange 5m candle stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.market_data.timeframes import Timeframe

AppKey = tuple[str, Timeframe]
NativeKey = tuple[str, Timeframe]


def native_key(key: AppKey) -> NativeKey:
    symbol, timeframe = key
    return symbol, timeframe.source


@dataclass
class SubscriptionChange:
    app_key_added: AppKey | None = None
    app_key_removed: AppKey | None = None
    native_added: NativeKey | None = None
    native_removed: NativeKey | None = None


@dataclass
class SubscriptionManager:
    _consumers: dict[AppKey, set[str]] = field(default_factory=dict)

    def acquire(self, consumer: str, key: AppKey) -> SubscriptionChange:
        change = SubscriptionChange()
        native = native_key(key)
        native_was_active = bool(self.app_keys_for_native(native))
        consumers = self._consumers.get(key)
        if consumers is None:
            consumers = set()
            self._consumers[key] = consumers
            change.app_key_added = key
            if not native_was_active:
                change.native_added = native
        consumers.add(consumer)
        return change

    def release(self, consumer: str, key: AppKey) -> SubscriptionChange:
        change = SubscriptionChange()
        consumers = self._consumers.get(key)
        if consumers is None or consumer not in consumers:
            return change
        consumers.discard(consumer)
        if not consumers:
            del self._consumers[key]
            change.app_key_removed = key
            if not self.app_keys_for_native(native_key(key)):
                change.native_removed = native_key(key)
        return change

    def release_all(self, consumer: str) -> list[SubscriptionChange]:
        keys = [k for k, consumers in self._consumers.items() if consumer in consumers]
        return [self.release(consumer, k) for k in keys]

    def consumers_of(self, key: AppKey) -> set[str]:
        return set(self._consumers.get(key, ()))

    def consumers_of_symbol(self, symbol: str) -> set[str]:
        result: set[str] = set()
        for (sym, _), consumers in self._consumers.items():
            if sym == symbol:
                result |= consumers
        return result

    def app_keys_for_native(self, native: NativeKey) -> list[AppKey]:
        return [k for k in self._consumers if native_key(k) == native]

    def keys_of(self, consumer: str) -> list[AppKey]:
        return [k for k, consumers in self._consumers.items() if consumer in consumers]

    @property
    def app_keys(self) -> list[AppKey]:
        return list(self._consumers)

    @property
    def native_keys(self) -> set[NativeKey]:
        return {native_key(k) for k in self._consumers}

    @property
    def symbols(self) -> set[str]:
        return {symbol for symbol, _ in self._consumers}
