import type { AnalysisSnapshot } from '@/types/analysis';

function fmt(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (typeof value === 'string' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

/** Development-only view of engine internals (rendered only when import.meta.env.DEV). */
export function AnalysisDebug({ snapshot }: { snapshot: AnalysisSnapshot | null }) {
  if (!snapshot) return null;
  const rows: [string, unknown][] = [
    ['symbol / tf', `${snapshot.symbol} ${snapshot.timeframe}`],
    ['candles', snapshot.candles_analyzed],
    ['candle_time', snapshot.candle_time],
    ...Object.entries(snapshot.debug ?? {}),
    ...Object.entries(snapshot.regime?.inputs ?? {}).map(
      ([k, v]) => [`regime.${k}`, v] as [string, unknown],
    ),
    ...Object.entries(snapshot.counts ?? {}).map(
      ([k, v]) => [`count.${k}`, v] as [string, unknown],
    ),
  ];
  return (
    <div
      dir="ltr"
      aria-label="debug"
      className="bg-sunken border-line mt-2 grid max-h-48 grid-cols-2 gap-x-4 overflow-auto rounded-lg border p-2 font-mono text-[10px] @5xl:grid-cols-3"
    >
      {rows.map(([key, value]) => (
        <div key={key} className="flex min-w-0 gap-2">
          <span className="text-fg-subtle shrink-0">{key}</span>
          <span className="text-fg-muted truncate" title={fmt(value)}>
            {fmt(value)}
          </span>
        </div>
      ))}
    </div>
  );
}
