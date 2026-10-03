import { ChevronDown, Search } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';

import { cn } from '@/lib/cn';
import type { SymbolCode } from '@/types/market';

const SYMBOL_PATTERN = /^[A-Z0-9]{2,20}USDT$/;

interface SymbolSelectorProps {
  value: SymbolCode;
  onChange: (symbol: SymbolCode) => void;
  /** Exchange symbol list. Empty until the market data provider exists (phase 2). */
  symbols?: readonly SymbolCode[];
}

export function SymbolSelector({ value, onChange, symbols = [] }: SymbolSelectorProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const inputId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const normalized = query.trim().toUpperCase().replace(/[-_/]/g, '');
  const matches = symbols.filter((s) => s.includes(normalized)).slice(0, 50);
  const canApply = SYMBOL_PATTERN.test(normalized);

  const apply = (symbol: SymbolCode) => {
    onChange(symbol);
    setQuery('');
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
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
        <div
          role="dialog"
          aria-label="اختيار الرمز"
          className="bg-surface-strong shadow-pop border-line absolute start-0 top-9 z-30 w-64 rounded-lg border p-2"
        >
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (canApply) apply(normalized);
            }}
          >
            <label htmlFor={inputId} className="sr-only">
              ابحث عن رمز
            </label>
            <div className="bg-sunken border-line focus-within:border-accent flex items-center gap-2 rounded-md border px-2">
              <Search className="text-fg-subtle size-3.5" />
              <input
                id={inputId}
                autoFocus
                dir="ltr"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                }}
                placeholder="BTCUSDT"
                className="text-fg placeholder:text-fg-subtle h-8 w-full bg-transparent text-sm outline-none"
                autoComplete="off"
                spellCheck={false}
              />
            </div>
          </form>

          <div className="mt-2 max-h-56 overflow-y-auto">
            {matches.map((symbol) => (
              <button
                key={symbol}
                type="button"
                onClick={() => {
                  apply(symbol);
                }}
                className={cn(
                  'ns-ltr hover:bg-surface-hover block w-full rounded px-2 py-1.5 text-start text-sm',
                  symbol === value && 'text-accent',
                )}
              >
                {symbol}
              </button>
            ))}
            {symbols.length === 0 && (
              <p className="text-fg-subtle px-1 py-2 text-xs leading-5">
                قائمة العقود من BingX غير متاحة بعد. يمكنك كتابة الرمز يدوياً ثم الضغط على Enter.
              </p>
            )}
            {normalized && !canApply && (
              <p className="text-warning px-1 pb-1 text-xs">صيغة الرمز غير صحيحة (مثال: BTCUSDT)</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
