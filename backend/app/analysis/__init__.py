"""Market intelligence engine (Phase 3): deterministic, testable market-structure features.

One canonical implementation (`engine.MarketAnalyzer`) serves live analysis, replay, the
future scanner, backtester and signal engine. It produces structured ANALYSIS only; it never
produces trade signals, entries, stops or targets.
"""
