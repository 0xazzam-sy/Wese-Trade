import type { MarketSymbol } from '@/types/market';

/** Instant client-side search: "BTC", "btcusdt", "BTC-USDT", "btc/usdt" all match BTCUSDT. */
export function searchSymbols(symbols: readonly MarketSymbol[], query: string): MarketSymbol[] {
  const needle = query
    .trim()
    .toUpperCase()
    .replace(/[-_/\s]/g, '');
  if (!needle) return [...symbols];
  const matches = symbols.filter((s) => s.symbol.includes(needle) || s.base_asset.includes(needle));
  const rank = (s: MarketSymbol) =>
    s.symbol === needle || s.base_asset === needle ? 0 : s.base_asset.startsWith(needle) ? 1 : 2;
  return matches.sort((a, b) => rank(a) - rank(b) || a.symbol.localeCompare(b.symbol));
}
