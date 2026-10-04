/** Display-only formatting of decimal strings (values are never computed for trading). */

export type Direction = 'up' | 'down' | 'flat';

export function formatPrice(value: string | null | undefined, precision?: number): string {
  if (value === null || value === undefined || value === '') return '--';
  const n = Number(value);
  if (!Number.isFinite(n)) return '--';
  return n.toLocaleString('en-US', {
    minimumFractionDigits: precision ?? 0,
    maximumFractionDigits: precision ?? 8,
  });
}

/** 24h % change; uses the live price against the 24h open when both are available. */
export function changePercent(
  live: string | null,
  openPrice: string | null | undefined,
  fallbackPercent: string | null | undefined,
): number | null {
  const open = Number(openPrice);
  const last = Number(live);
  if (live !== null && openPrice && Number.isFinite(open) && open > 0 && Number.isFinite(last)) {
    return ((last - open) / open) * 100;
  }
  const fallback = Number(fallbackPercent);
  return fallbackPercent != null && Number.isFinite(fallback) ? fallback : null;
}

export function direction(percent: number | null): Direction {
  if (percent === null || Math.abs(percent) < 0.005) return 'flat';
  return percent > 0 ? 'up' : 'down';
}

export function formatPercent(percent: number | null): string {
  if (percent === null) return '--';
  const rounded = Math.abs(percent) < 0.005 ? 0 : percent;
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(2)}%`;
}

export function compactNumber(value: string | null | undefined): string {
  const n = Number(value);
  if (value == null || !Number.isFinite(n)) return '--';
  return n.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 2 });
}
