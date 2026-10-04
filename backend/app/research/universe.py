"""Research symbol universe: chosen by liquidity and history, never by strategy results.

Rule (deterministic, documented in docs/research.md):
1. live linear USDT perpetual swaps whose OKX `instCategory` is crypto ("1");
2. listed at least `min_listing_days` before the selection date (history for warm-up +
   a full year of research data);
3. pre-rank the 40 most traded by 24h quote volume, then rank by the MEAN daily quote
   volume of the last 30 closed daily candles (one 24h snapshot is too noisy);
4. BTC, ETH, SOL are always included as anchors; the next `extra` symbols are added.

Known bias: only currently-listed instruments are eligible (survivorship), and current
liquidity is used. Strategy performance is never an input.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.market_data.okx.rest import OkxRestClient
from app.research.store import RESEARCH_DIR

ANCHORS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
UNIVERSE_PATH = RESEARCH_DIR / "universe.json"


@dataclass(frozen=True, slots=True)
class UniverseMember:
    symbol: str
    inst_id: str
    tick_size: float
    listed_ms: int
    mean_daily_quote_volume: float
    anchor: bool


def to_symbol(inst_id: str) -> str:
    return inst_id.replace("-SWAP", "").replace("-", "")


def eligible(inst: dict[str, Any], now_ms: int, min_listing_days: int) -> bool:
    return (
        inst.get("state") == "live"
        and inst.get("ctType") == "linear"
        and inst.get("settleCcy") == "USDT"
        and str(inst.get("instCategory", "1")) == "1"
        and str(inst.get("instId", "")).endswith("-USDT-SWAP")
        and now_ms - int(inst.get("listTime") or now_ms) >= min_listing_days * 86_400_000
    )


def rank(
    members: list[UniverseMember], extra: int, anchors: tuple[str, ...] = ANCHORS
) -> list[UniverseMember]:
    """Anchors first, then the most liquid others by mean daily quote volume."""
    by_symbol = {m.symbol: m for m in members}
    chosen = [by_symbol[a] for a in anchors if a in by_symbol]
    others = sorted(
        (m for m in members if m.symbol not in anchors),
        key=lambda m: (-m.mean_daily_quote_volume, m.symbol),
    )
    return chosen + others[:extra]


async def select(
    rest: OkxRestClient, *, extra: int = 9, min_listing_days: int = 400, prerank: int = 40
) -> list[UniverseMember]:
    now_ms = int(time.time() * 1000)
    instruments = await rest.get("/api/v5/public/instruments", {"instType": "SWAP"})
    tickers = await rest.get("/api/v5/market/tickers", {"instType": "SWAP"})
    inst = {i["instId"]: i for i in instruments if eligible(i, now_ms, min_listing_days)}
    vol24 = sorted(
        (
            (float(t["volCcy24h"]) * float(t["last"]), t["instId"])
            for t in tickers
            if t["instId"] in inst
        ),
        reverse=True,
    )
    candidates = {inst_id for _, inst_id in vol24[:prerank]}
    candidates |= {f"{a[:-4]}-USDT-SWAP" for a in ANCHORS}
    members: list[UniverseMember] = []
    for inst_id in sorted(candidates):
        if inst_id not in inst:
            continue
        rows = await rest.get(
            "/api/v5/market/history-candles", {"instId": inst_id, "bar": "1Dutc", "limit": 31}
        )
        closed = [r for r in rows if r[8] == "1"][:30]
        if not closed:
            continue
        mean_qv = sum(float(r[7]) for r in closed) / len(closed)
        symbol = to_symbol(inst_id)
        members.append(
            UniverseMember(
                symbol=symbol,
                inst_id=inst_id,
                tick_size=float(inst[inst_id]["tickSz"]),
                listed_ms=int(inst[inst_id]["listTime"]),
                mean_daily_quote_volume=mean_qv,
                anchor=symbol in ANCHORS,
            )
        )
    return rank(members, extra)


def save(members: list[UniverseMember], path: Path = UNIVERSE_PATH, **meta: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"selected_at_ms": int(time.time() * 1000), **meta}
    payload["members"] = [asdict(m) for m in members]
    path.write_text(json.dumps(payload, indent=2))


def load(path: Path = UNIVERSE_PATH) -> list[UniverseMember]:
    data = json.loads(path.read_text())
    return [UniverseMember(**m) for m in data["members"]]
