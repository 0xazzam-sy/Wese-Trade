import { ChevronDown, Search } from 'lucide-react';
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from 'react';

import { Spinner } from '@/components/ui/Spinner';
import { VirtualList } from '@/components/ui/VirtualList';
import { useSymbols, useTickerMap } from '@/features/markets/queries';
import { searchSymbols } from '@/features/markets/search';
import { cn } from '@/lib/cn';
import { changePercent, direction, formatPercent, formatPrice } from '@/lib/marketFormat';
import type { MarketSymbol, SymbolCode } from '@/types/market';

const ROW_HEIGHT = 36;
const LIST_HEIGHT = 288;

interface SymbolSelectorProps {
  value: SymbolCode;
  onChange: (symbol: SymbolCode) => void;
}

/** Searchable, keyboard-accessible, virtualized list of all active OKX USDT perpetual swaps. */
export function SymbolSelector({ value, onChange }: SymbolSelectorProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const symbols = useSymbols();
  const tickers = useTickerMap();

  // Not deferred: Enter must always select from the results for the text just typed.
  // Filtering a few hundred symbols synchronously is cheap; rendering is virtualized.
  const results = useMemo(
    () => searchSymbols(symbols.data?.items ?? [], query),
    [symbols.data, query],
  );

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  const choose = (symbol: MarketSymbol | undefined) => {
    if (!symbol) return;
    onChange(symbol.symbol);
    setQuery('');
    setOpen(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => Math.min(results.length - 1, i + 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      choose(results[active]);
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`اختيار العقد، الحالي ${value}`}
        onClick={() => {
          setOpen((o) => !o);
        }}
        className="hover:bg-surface-hover flex h-7 items-center gap-1.5 rounded-md px-2 transition-colors"
      >
        <span className="ns-ltr text-fg text-sm font-semibold">{value}</span>
        <span className="text-fg-subtle text-2xs">دائم</span>
        <ChevronDown className="text-fg-subtle size-3.5" />
      </button>

      {open && (
        <div className="bg-surface-strong shadow-pop border-line absolute start-0 top-9 z-30 w-80 rounded-lg border p-2">
          <div className="bg-sunken border-line focus-within:border-accent flex items-center gap-2 rounded-md border px-2">
            <Search className="text-fg-subtle size-3.5" />
            <input
              autoFocus
              dir="ltr"
              role="combobox"
              aria-label="ابحث عن عقد"
              aria-controls={listId}
              aria-expanded="true"
              aria-activedescendant={
                results[active] ? `${listId}-${results[active].symbol}` : undefined
              }
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              placeholder="BTC, ETH, SOL…"
              className="text-fg placeholder:text-fg-subtle h-8 w-full bg-transparent text-sm outline-none"
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          <div className="text-fg-subtle text-2xs mt-2 flex justify-between px-1">
            <span>العقد</span>
            <span>السعر · 24س</span>
          </div>

          {symbols.isPending ? (
            <div className="flex h-24 items-center justify-center">
              <Spinner />
            </div>
          ) : symbols.isError ? (
            <p className="text-bear px-1 py-4 text-xs">تعذر تحميل قائمة العقود.</p>
          ) : results.length === 0 ? (
            <p className="text-fg-subtle px-1 py-4 text-xs">لا توجد نتائج مطابقة.</p>
          ) : (
            <VirtualList
              id={listId}
              role="listbox"
              ariaLabel="العقود"
              className="mt-1"
              items={results}
              rowHeight={ROW_HEIGHT}
              height={Math.min(LIST_HEIGHT, results.length * ROW_HEIGHT)}
              activeIndex={active}
              getKey={(s) => s.symbol}
              renderRow={(s, index) => {
                const ticker = tickers.get(s.symbol);
                const pct = changePercent(null, null, ticker?.price_change_percent);
                const dir = direction(pct);
                return (
                  <div
                    id={`${listId}-${s.symbol}`}
                    role="option"
                    aria-selected={s.symbol === value}
                    onPointerDown={(e) => {
                      e.preventDefault();
                      choose(s);
                    }}
                    onPointerEnter={() => {
                      setActive(index);
                    }}
                    className={cn(
                      'flex h-full cursor-pointer items-center gap-2 rounded px-2',
                      index === active && 'bg-surface-hover',
                    )}
                  >
                    <span className="ns-ltr flex items-baseline gap-1">
                      <span
                        className={cn('text-sm font-semibold', s.symbol === value && 'text-accent')}
                      >
                        {s.base_asset}
                      </span>
                      <span className="text-fg-subtle text-2xs">/{s.quote_asset}</span>
                    </span>
                    <span className="ns-num text-fg-muted ms-auto text-xs">
                      {formatPrice(ticker?.last_price, s.price_precision)}
                    </span>
                    <span
                      className={cn(
                        'ns-num w-16 text-end text-xs',
                        dir === 'up' && 'text-bull',
                        dir === 'down' && 'text-bear',
                        dir === 'flat' && 'text-fg-subtle',
                      )}
                    >
                      {formatPercent(pct)}
                    </span>
                  </div>
                );
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
