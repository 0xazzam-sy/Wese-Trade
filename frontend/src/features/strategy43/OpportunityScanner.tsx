import { useQuery } from '@tanstack/react-query';
import { Radar } from 'lucide-react';

import { useSymbolMap } from '@/features/markets/queries';
import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/marketFormat';
import { strategy43Api } from '@/services/api/strategy43';
import { useAnalysisStore } from '@/stores/analysisStore';
import { useChartStore } from '@/stores/chartStore';
import type { Timeframe } from '@/types/market';
import { TIER_STYLE, type OpportunityDTO } from '@/types/strategy43';

import { ago, S43_AR } from './labels';

/**
 * «أفضل الفرص الآن»: open confirmed Strategy 4.3 opportunities across the scanned market,
 * ranked by the backend (tier, freshness, score, R:R). Click a row to open it on the
 * focused chart. The scanner never creates signals; it only lists confirmed ones.
 */
export function OpportunityScanner() {
  const symbols = useSymbolMap();
  const focused = useAnalysisStore((s) => s.focused);
  const setSymbol = useChartStore((s) => s.setSymbol);
  const setTimeframe = useChartStore((s) => s.setTimeframe);
  const { data, isError } = useQuery({
    queryKey: ['strategy43', 'opportunities'],
    queryFn: ({ signal }) => strategy43Api.opportunities(20, signal),
    refetchInterval: 15_000,
    retry: false,
  });
  const open = (o: OpportunityDTO) => {
    setSymbol(focused, o.symbol);
    setTimeframe(focused, o.timeframe as Timeframe);
  };
  const items = data?.items ?? [];
  return (
    <section
      aria-label={S43_AR.scannerTitle}
      data-testid="opportunity-scanner"
      className="ns-panel flex min-h-0 shrink-0 flex-col p-3"
    >
      <header className="mb-1.5 flex items-center gap-2">
        <Radar className="text-accent size-4" />
        <h2 className="text-sm font-semibold">{S43_AR.scannerTitle}</h2>
        {data && (
          <span className="text-fg-subtle text-2xs ms-auto" data-testid="scanner-coverage">
            {data.symbols_with_opportunity} / {data.universe_size} عملة
          </span>
        )}
      </header>
      {isError ? (
        <p className="text-fg-subtle text-2xs">{S43_AR.scannerError}</p>
      ) : !data || data.state === 'starting' ? (
        <p className="text-fg-subtle text-2xs">{S43_AR.scannerStarting}</p>
      ) : items.length === 0 ? (
        <p className="text-fg-subtle text-2xs" data-testid="scanner-empty">
          {S43_AR.scannerEmpty}
        </p>
      ) : (
        <ol className="ns-scroll -mx-1 flex max-h-56 flex-col overflow-y-auto 2xl:max-h-72">
          {items.map((o, i) => (
            <li key={o.id}>
              <button
                type="button"
                data-testid="scanner-row"
                data-symbol={o.symbol}
                data-timeframe={o.timeframe}
                onClick={() => {
                  open(o);
                }}
                title={`${o.family_ar} · ${o.state_ar} · الدخول ${formatPrice(
                  String(o.entry),
                  symbols.get(o.symbol)?.price_precision,
                )} · R:R ${o.rr[1].toFixed(1)}`}
                className="hover:bg-sunken flex w-full min-w-0 items-center gap-1.5 rounded-md px-1 py-1 text-start text-xs"
              >
                <span className="ns-num text-fg-subtle w-4 shrink-0">{i + 1}</span>
                <span className="ns-ltr min-w-0 flex-1 truncate font-medium">{o.symbol}</span>
                <span
                  className={cn(
                    'w-9 shrink-0 font-semibold',
                    o.side === 'BUY' ? 'text-bull' : 'text-bear',
                  )}
                >
                  {o.side}
                </span>
                <span className="ns-ltr text-fg-muted w-7 shrink-0">{o.timeframe}</span>
                <span
                  className={cn(
                    'text-2xs w-6 shrink-0 rounded border text-center',
                    TIER_STYLE[o.tier],
                  )}
                >
                  {o.tier}
                </span>
                <span className="ns-num w-6 shrink-0 text-end font-semibold">
                  {Math.round(o.score)}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
      {data && (
        <p className="text-fg-subtle text-2xs mt-1.5">
          {S43_AR.lastScan}: {ago(data.last_scan_at)} · {S43_AR.scoreHint}
        </p>
      )}
    </section>
  );
}
