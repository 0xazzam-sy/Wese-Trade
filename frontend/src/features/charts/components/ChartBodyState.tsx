import { AlertTriangle, Ban, CandlestickChart as CandlesIcon } from 'lucide-react';

import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import type { ChartLoadState } from '@/features/charts/hooks/useMarketChart';

/** Skeleton shown while history loads, so old candles are never shown under a new header. */
function CandleSkeleton() {
  const heights = [38, 52, 30, 64, 46, 72, 40, 58, 34, 66, 50, 44, 70, 36, 60, 48];
  return (
    <div aria-hidden className="flex h-24 items-end gap-1.5 opacity-60">
      {heights.map((h, i) => (
        <span
          key={i}
          className="bg-line-strong w-2 animate-pulse rounded-sm"
          style={{ height: `${h}%`, animationDelay: `${i * 60}ms` }}
        />
      ))}
    </div>
  );
}

export function ChartBodyState({
  load,
  symbol,
  onRetry,
}: {
  load: ChartLoadState;
  symbol: string;
  onRetry: () => void;
}) {
  if (load.status === 'ready' && !load.empty) return null;

  let content;
  if (load.status === 'loading') {
    content = (
      <div className="flex flex-col items-center gap-3" role="status">
        <CandleSkeleton />
        <p className="text-fg-muted text-xs">
          جاري تحميل شموع <span className="ns-ltr">{symbol}</span>…
        </p>
      </div>
    );
  } else if (load.status === 'unavailable') {
    content = (
      <EmptyState
        compact
        icon={<Ban className="size-5" />}
        title="هذا العقد غير متاح حالياً"
        description="قد يكون العقد موقوفاً أو أُزيل من OKX. اختر عقداً آخر."
      />
    );
  } else if (load.status === 'error') {
    const description =
      load.code === 'rate_limited'
        ? 'تم تجاوز حد الطلبات مؤقتاً. أعد المحاولة بعد قليل.'
        : load.code === 'loading_metadata'
          ? 'جاري تحميل قائمة العقود من OKX.'
          : 'تعذر تحميل بيانات السوق من OKX.';
    content = (
      <div className="flex flex-col items-center gap-2">
        <EmptyState
          compact
          icon={<AlertTriangle className="size-5" />}
          title="تعذر تحميل الشموع"
          description={description}
        />
        <Button className="pointer-events-auto h-8" onClick={onRetry}>
          إعادة المحاولة
        </Button>
      </div>
    );
  } else {
    content = (
      <EmptyState
        compact
        icon={<CandlesIcon className="size-5" />}
        title="لا توجد شموع لهذا العقد"
      />
    );
  }

  return (
    <div className="bg-bg/60 pointer-events-none absolute inset-0 z-10 flex items-center justify-center overflow-hidden backdrop-blur-[1px]">
      {content}
    </div>
  );
}
