import { useQuery } from '@tanstack/react-query';
import { Info } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { IconButton } from '@/components/ui/IconButton';
import { Spinner } from '@/components/ui/Spinner';
import { formatShortDateTime } from '@/lib/format';
import { compactNumber, formatPrice } from '@/lib/marketFormat';
import { marketsApi } from '@/services/api/markets';

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <span className="text-fg-subtle text-xs">{label}</span>
      <span className="ns-num text-fg text-xs">{value}</span>
    </div>
  );
}

/** Instrument metadata + funding + open interest + best bid/ask. Fetched only while open. */
export function ContractInfo({ symbol }: { symbol: string }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const details = useQuery({
    queryKey: ['markets', 'details', symbol],
    queryFn: ({ signal }) => marketsApi.details(symbol, signal),
    enabled: open,
    refetchInterval: open ? 30_000 : false,
  });

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

  const d = details.data;
  const precision = d?.symbol.price_precision;
  const fundingPct = d?.funding ? `${(Number(d.funding.funding_rate) * 100).toFixed(4)}%` : '--';

  return (
    <div ref={rootRef} className="relative">
      <IconButton
        size="sm"
        label="معلومات العقد"
        active={open}
        onClick={() => {
          setOpen((o) => !o);
        }}
        icon={<Info className="size-3.5" />}
      />
      {open && (
        <div
          role="dialog"
          aria-label="معلومات العقد"
          className="bg-surface-strong shadow-pop border-line absolute end-0 top-9 z-30 w-72 rounded-lg border p-3"
        >
          <p className="ns-ltr mb-2 text-sm font-semibold">{symbol}</p>
          {details.isPending ? (
            <div className="flex justify-center py-4">
              <Spinner />
            </div>
          ) : details.isError || !d ? (
            <p className="text-bear text-xs">تعذر تحميل بيانات العقد.</p>
          ) : (
            <div className="divide-line divide-y">
              <Row label="حجم التيك" value={d.symbol.tick_size} />
              <Row
                label="قيمة العقد"
                value={
                  d.symbol.contract_value
                    ? `${d.symbol.contract_value} ${d.symbol.contract_value_currency ?? ''}`
                    : '--'
                }
              />
              <Row
                label="أقصى رافعة"
                value={d.symbol.max_leverage ? `${d.symbol.max_leverage}x` : '--'}
              />
              <Row label="سعر العلامة" value={formatPrice(d.funding?.mark_price, precision)} />
              <Row label="سعر المؤشر" value={formatPrice(d.funding?.index_price, precision)} />
              <Row label="معدل التمويل" value={fundingPct} />
              <Row
                label="التمويل القادم"
                value={
                  d.funding?.next_funding_time
                    ? formatShortDateTime(new Date(d.funding.next_funding_time))
                    : '--'
                }
              />
              <Row
                label="العقود المفتوحة"
                value={
                  d.open_interest?.base
                    ? `${compactNumber(d.open_interest.base)} ${d.symbol.base_asset}`
                    : '--'
                }
              />
              <Row
                label="العقود المفتوحة (USD)"
                value={d.open_interest?.usd ? `$${compactNumber(d.open_interest.usd)}` : '--'}
              />
              <Row label="أفضل عرض شراء" value={formatPrice(d.book?.bid, precision)} />
              <Row label="أفضل عرض بيع" value={formatPrice(d.book?.ask, precision)} />
              <Row label="الفارق" value={formatPrice(d.book?.spread, precision)} />
              <Row
                label="حجم التداول 24س"
                value={
                  d.ticker ? `${compactNumber(d.ticker.volume_24h)} ${d.symbol.base_asset}` : '--'
                }
              />
            </div>
          )}
          <p className="text-fg-subtle text-2xs mt-2">
            للاطلاع فقط — لا يُستخدم في أي تحليل حالياً.
          </p>
        </div>
      )}
    </div>
  );
}
