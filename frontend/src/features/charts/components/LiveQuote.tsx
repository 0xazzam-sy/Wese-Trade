import { useLivePrice } from '@/features/charts/hooks/useLivePrice';
import { useTickerMap } from '@/features/markets/queries';
import { cn } from '@/lib/cn';
import { changePercent, direction, formatPercent, formatPrice } from '@/lib/marketFormat';
import type { MarketSymbol } from '@/types/market';

/**
 * Last price (realtime ticks) + 24h change. Only this component re-renders on ticks.
 * Colors describe price direction only — never a trade signal.
 */
export function LiveQuote({ symbol, meta }: { symbol: string; meta: MarketSymbol | undefined }) {
  const live = useLivePrice(symbol);
  const ticker = useTickerMap().get(symbol);
  const last = live ?? ticker?.last_price ?? null;
  const pct = changePercent(live, ticker?.open_price, ticker?.price_change_percent);
  const dir = direction(pct);
  const precision = meta?.price_precision;

  return (
    <div className="flex items-baseline gap-2" aria-live="off">
      <span
        className={cn(
          'ns-num text-sm font-semibold',
          dir === 'up' && 'text-bull',
          dir === 'down' && 'text-bear',
          dir === 'flat' && 'text-fg',
        )}
        title="آخر سعر"
      >
        {formatPrice(last, precision)}
      </span>
      <span
        className={cn(
          'ns-num rounded px-1 text-xs',
          dir === 'up' && 'bg-bull-soft text-bull',
          dir === 'down' && 'bg-bear-soft text-bear',
          dir === 'flat' && 'bg-neutral-soft text-fg-muted',
        )}
        title="التغير خلال 24 ساعة"
      >
        {formatPercent(pct)}
      </span>
      {ticker && (
        <span className="text-fg-subtle text-2xs hidden gap-2 @3xl:flex">
          <span>
            أعلى 24س{' '}
            <span className="ns-num text-fg-muted">{formatPrice(ticker.high_24h, precision)}</span>
          </span>
          <span>
            أدنى 24س{' '}
            <span className="ns-num text-fg-muted">{formatPrice(ticker.low_24h, precision)}</span>
          </span>
        </span>
      )}
    </div>
  );
}
