import { Radar, Search, SlidersHorizontal } from 'lucide-react';

import { EmptyState } from '@/components/ui/EmptyState';
import { Panel } from '@/components/ui/Panel';
import { SegmentedControl } from '@/components/ui/SegmentedControl';

const SIGNAL_FILTERS = [
  { value: 'all', label: 'الكل' },
  { value: 'buy', label: 'شراء' },
  { value: 'sell', label: 'بيع' },
  { value: 'neutral', label: 'محايد' },
] as const;

/**
 * Market scanner shell. Controls are visible but disabled until the backend scanner
 * exists; no rows, prices, signals or scores are fabricated.
 */
export function ScannerSidebar() {
  return (
    <Panel
      as="aside"
      aria-label="ماسح السوق"
      title="ماسح السوق"
      icon={<Radar className="size-4" />}
      actions={
        <span className="bg-neutral-soft text-fg-subtle text-2xs rounded-full px-2 py-0.5">
          غير مفعّل
        </span>
      }
      className="h-full"
      bodyClassName="flex flex-col"
    >
      <div className="border-line space-y-2.5 border-b p-3">
        <label className="bg-sunken border-line flex items-center gap-2 rounded-lg border px-2.5 opacity-60">
          <Search className="text-fg-subtle size-3.5" />
          <span className="sr-only">ابحث عن عقد</span>
          <input
            disabled
            placeholder="ابحث عن عقد… (مثال: BTCUSDT)"
            className="placeholder:text-fg-subtle h-8 w-full bg-transparent text-sm outline-none disabled:cursor-not-allowed"
          />
        </label>
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="text-fg-subtle size-3.5 shrink-0" />
          <fieldset disabled className="min-w-0 flex-1 opacity-60">
            <legend className="sr-only">تصفية حسب الإشارة</legend>
            <SegmentedControl
              size="sm"
              ariaLabel="تصفية حسب الإشارة"
              value="all"
              options={SIGNAL_FILTERS}
              onChange={() => undefined}
              className="w-full [&>button]:flex-1"
            />
          </fieldset>
        </div>
      </div>

      <div
        role="row"
        className="border-line text-fg-subtle text-2xs grid grid-cols-[1.3fr_1fr_0.9fr_0.6fr] gap-2 border-b px-3 py-2 font-medium"
      >
        <span role="columnheader">الرمز</span>
        <span role="columnheader">السعر</span>
        <span role="columnheader">الإشارة</span>
        <span role="columnheader" className="text-end">
          الثقة
        </span>
      </div>

      <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto">
        <EmptyState
          icon={<Radar className="size-5" />}
          title="الماسح غير مفعّل بعد"
          description="ستظهر عقود BingX الدائمة هنا مع السعر والإشارة ودرجة الثقة بعد تفعيل محرك المسح في مرحلة لاحقة."
        />
      </div>
    </Panel>
  );
}
