"""Signal engine (Phase 4): transparent, deterministic, testable signals from Phase 3 analysis.

One canonical `SignalEngine` (pure evaluation) + `SignalTracker` (cooldown, dedupe,
lifecycle) serve live Wese Trade, historical replay, backtesting and the future scanner.

A signal score (e.g. 87/100) is a CONFLUENCE / setup-quality score. It is NOT a
probability of profit and must never be presented as one.
"""
