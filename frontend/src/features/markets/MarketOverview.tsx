import { LineChart, Search } from 'lucide-react';
import { useDeferredValue, useMemo, useState } from 'react';

import { EmptyState } from '@/components/ui/EmptyState';
import { Panel } from '@/components/ui/Panel';
import { Spinner } from '@/components/ui/Spinner';
import { VirtualList } from '@/components/ui/VirtualList';
import { cn } from '@/lib/cn';
import { changePercent, direction, formatPercent, formatPrice } from '@/lib/marketFormat';
import { useChartStore } from '@/stores/chartStore';
import type { MarketSymbol, Ticker } from '@/types/market';

import { useSymbols, useTickers } from './queries';
import { searchSymbols } from './search';

const ROW_HEIGHT = 34;

interface Row {
  symbol: MarketSymbol;
  ticker: Ticker | undefined;
}

/**
 * Market overview (NOT a scanner): real OKX prices and 24h change only.
 * Signal and confidence columns stay "--" until the signal engine exists.
 * Sorted by 24h turnover (base volume × last price) — a liquidity ordering, not a ranking.
 */
export function MarketOverview() {
  const [query, setQuery] = useState('');
  const deferred = useDeferredValue(query);
  const [height, setHeight] = useState(400);
  const symbols = useSymbols();
  const tickers = useTickers();
  const selected = useChartStore((s) => s.charts.primary.symbol);
  const setSymbol = useChartStore((s) => s.setSymbol);

  const rows = useMemo<Row[]>(() => {
    const tickerMap = new Map((tickers.data?.items ?? []).map((t) => [t.symbol, t]));
    const matched = searchSymbols(symbols.data?.items ?? [], deferred).map((s) => ({
      symbol: s,
      ticker: tickerMap.get(s.symbol),
    }));
    if (!deferred) {
      // Liquidity ordering only (not a ranking): base volume x last price.
      const turnover = (t: Ticker | undefined) =>
        t ? Number(t.volume_24h) * Number(t.last_price) || 0 : 0;
      matched.sort((a, b) => turnover(b.ticker) - turnover(a.ticker));
    }
    return matched;
  }, [symbols.data, tickers.data, deferred]);

  return (
    <Panel
      as="aside"
      aria-label="نظرة على السوق"
      title="نظرة على السوق"
      icon={<LineChart className="size-4" />}
      actions={
        <span
          className="bg-neutral-soft text-fg-subtle text-2xs rounded-full px-2 py-0.5"
          title="الماسح غير مفعّل بعد"
        >
          بدون إشارات
        </span>
      }
      className="h-full"
      bodyClassName="flex flex-col"
    >
      <div className="border-line border-b p-3">
        <label className="bg-sunken border-line focus-within:border-accent flex items-center gap-2 rounded-lg border px-2.5">
          <Search className="text-fg-subtle size-3.5" />
          <span className="sr-only">ابحث عن عقد</span>
          <input
            dir="ltr"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
            }}
            placeholder="BTC, ETH…"
            className="placeholder:text-fg-subtle h-8 w-full bg-transparent text-sm outline-none"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <p className="text-fg-subtle text-2xs mt-2">
          {symbols.data ? `${symbols.data.total} عقداً دائماً · مرتبة حسب حجم التداول` : ' '}
        </p>
      </div>

      <div className="border-line text-fg-subtle text-2xs grid grid-cols-[1.2fr_1.1fr_0.9fr_0.5fr_0.4fr] gap-1 border-b px-3 py-2 font-medium">
        <span>الرمز</span>
        <span>السعر</span>
        <span>24س</span>
        <span>الإشارة</span>
        <span className="text-end">الثقة</span>
      </div>

      <div
        className="min-h-0 flex-1"
        ref={(el) => {
          if (el?.clientHeight && el.clientHeight !== height) setHeight(el.clientHeight);
        }}
      >
        {symbols.isPending ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : symbols.isError ? (
          <EmptyState
            compact
            title="تعذر تحميل بيانات السوق"
            description="سيعاد المحاولة تلقائياً."
          />
        ) : rows.length === 0 ? (
          <EmptyState compact title="لا توجد نتائج مطابقة" />
        ) : (
          <VirtualList
            items={rows}
            rowHeight={ROW_HEIGHT}
            height={height}
            getKey={(r) => r.symbol.symbol}
            ariaLabel="قائمة العقود"
            role="list"
            renderRow={({ symbol, ticker }) => {
              const pct = changePercent(null, null, ticker?.price_change_percent);
              const dir = direction(pct);
              return (
                <button
                  type="button"
                  role="listitem"
                  onClick={() => {
                    setSymbol('primary', symbol.symbol);
                  }}
                  title="عرض في الرسم الرئيسي"
                  className={cn(
                    'hover:bg-surface-hover grid h-full w-full grid-cols-[1.2fr_1.1fr_0.9fr_0.5fr_0.4fr] items-center gap-1 px-3 text-start',
                    symbol.symbol === selected && 'bg-accent-soft',
                  )}
                >
                  <span className="ns-ltr truncate text-start text-xs font-semibold">
                    {symbol.base_asset}
                  </span>
                  <span className="ns-num text-fg-muted truncate text-start text-xs">
                    {formatPrice(ticker?.last_price, symbol.price_precision)}
                  </span>
                  <span
                    className={cn(
                      'ns-num text-start text-xs',
                      dir === 'up' && 'text-bull',
                      dir === 'down' && 'text-bear',
                      dir === 'flat' && 'text-fg-subtle',
                    )}
                  >
                    {formatPercent(pct)}
                  </span>
                  <span className="ns-num text-fg-subtle text-xs">--</span>
                  <span className="ns-num text-fg-subtle text-end text-xs">--</span>
                </button>
              );
            }}
          />
        )}
      </div>
      {tickers.isError && (
        <p className="border-line text-warning text-2xs border-t px-3 py-1.5">
          تعذر تحديث الأسعار مؤقتاً.
        </p>
      )}
    </Panel>
  );
}
