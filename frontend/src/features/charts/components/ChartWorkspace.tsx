import { Columns2, Rows2 } from 'lucide-react';
import { type ReactNode, useEffect } from 'react';

import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { cn } from '@/lib/cn';
import { type ChartLayout, useLayoutStore } from '@/stores/layoutStore';

import { ChartPanel } from './ChartPanel';

const LAYOUT_OPTIONS = [
  { value: 'stacked', label: <Rows2 className="size-3.5" />, title: 'تخطيط عمودي' },
  { value: 'side-by-side', label: <Columns2 className="size-3.5" />, title: 'تخطيط جنباً إلى جنب' },
] as const satisfies readonly { value: ChartLayout; label: ReactNode; title: string }[];

export function ChartWorkspace() {
  const layout = useLayoutStore((s) => s.chartLayout);
  const setLayout = useLayoutStore((s) => s.setChartLayout);
  const maximized = useLayoutStore((s) => s.maximizedChart);
  const restore = useLayoutStore((s) => s.restore);

  useEffect(() => {
    if (!maximized) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') restore();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, [maximized, restore]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex items-center gap-2 px-0.5">
        <h2 className="text-fg-muted text-xs font-semibold">مساحة الرسوم البيانية</h2>
        <span className="text-fg-subtle text-2xs">التوقيت حسب منطقتك الزمنية</span>
        <SegmentedControl
          className="ms-auto"
          size="sm"
          ariaLabel="تخطيط الرسوم البيانية"
          value={layout}
          options={LAYOUT_OPTIONS}
          onChange={setLayout}
        />
      </div>

      <div
        data-layout={layout}
        className={cn(
          'grid min-h-0 flex-1 gap-2',
          maximized
            ? 'grid-cols-1 grid-rows-1'
            : layout === 'stacked'
              ? 'grid-cols-1 grid-rows-[minmax(0,3fr)_minmax(0,2fr)]'
              : 'grid-cols-[minmax(0,3fr)_minmax(0,2fr)] grid-rows-1',
        )}
      >
        <ChartPanel chartId="primary" className={cn(maximized === 'secondary' && 'hidden')} />
        <ChartPanel chartId="secondary" className={cn(maximized === 'primary' && 'hidden')} />
      </div>
    </div>
  );
}
