import { Activity, Info } from 'lucide-react';

interface Metric {
  label: string;
  /** Shorter Arabic label used when the panel is narrow (e.g. 1366px screens). */
  short?: string;
  /** Latin financial abbreviation shown next to the Arabic label. */
  abbr?: string;
}

const PLAN_METRICS: Metric[] = [
  { label: 'سعر الدخول', abbr: 'Entry' },
  { label: 'وقف الخسارة', abbr: 'SL' },
  { label: 'الهدف الأول', abbr: 'TP1' },
  { label: 'الهدف الثاني', abbr: 'TP2' },
  { label: 'الهدف الثالث', abbr: 'TP3' },
  { label: 'نسبة المخاطرة إلى العائد', short: 'المخاطرة/العائد', abbr: 'R:R' },
];

const CONTEXT_METRICS: Metric[] = [
  { label: 'الاتجاه' },
  { label: 'الهيكل', abbr: 'BOS/CHoCH' },
  { label: 'السيولة' },
  { label: 'الزخم' },
  { label: 'التذبذب' },
];

const EMPTY_VALUE = '--';

function MetricCell({ metric }: { metric: Metric }) {
  return (
    <div
      title={metric.label}
      className="bg-sunken border-line flex min-w-0 flex-col gap-1 rounded-lg border px-2.5 py-2"
    >
      <span className="text-fg-subtle text-2xs flex items-center gap-1.5 truncate">
        {metric.short ? (
          <>
            <span className="@5xl:hidden">{metric.short}</span>
            <span className="hidden @5xl:inline">{metric.label}</span>
          </>
        ) : (
          metric.label
        )}
        {metric.abbr && (
          <span className="ns-ltr text-fg-subtle/70 hidden @5xl:inline">{metric.abbr}</span>
        )}
      </span>
      <span className="ns-num text-fg-muted text-sm font-medium">{EMPTY_VALUE}</span>
    </div>
  );
}

/**
 * Reserved signal panel. Phase 1 has no signal engine, so every value is an explicit
 * placeholder ("--"). Nothing here is computed in the browser.
 */
export function SignalPanel() {
  return (
    <section aria-label="لوحة الإشارة" className="ns-panel @container shrink-0 p-3">
      <div className="flex gap-3">
        <div className="border-line flex w-44 shrink-0 flex-col gap-2 border-e pe-3 @5xl:w-56">
          <div className="flex items-center gap-2">
            <Activity className="text-accent size-4" />
            <h2 className="text-sm font-semibold">الإشارة</h2>
          </div>
          <div className="bg-neutral-soft text-fg-muted rounded-lg px-3 py-2 text-center text-sm font-medium">
            لا توجد إشارة حالياً
          </div>
          <div>
            <div className="text-fg-subtle text-2xs mb-1 flex items-center justify-between">
              <span>قوة الإشارة</span>
              <span className="ns-num">{EMPTY_VALUE}</span>
            </div>
            <div
              className="bg-sunken border-line h-1.5 overflow-hidden rounded-full border"
              role="meter"
              aria-label="قوة الإشارة"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuetext="غير متاح"
            />
          </div>
        </div>

        <div className="grid min-w-0 flex-1 grid-cols-6 gap-2">
          {PLAN_METRICS.map((m) => (
            <MetricCell key={m.label} metric={m} />
          ))}
          <div className="col-span-6 grid grid-cols-5 gap-2">
            {CONTEXT_METRICS.map((m) => (
              <MetricCell key={m.label} metric={m} />
            ))}
          </div>
        </div>
      </div>
      <p className="text-fg-subtle text-2xs mt-2 flex items-center gap-1.5">
        <Info className="size-3" />
        قوة الإشارة ستمثل درجة توافق شروط الاستراتيجية، وليست احتمالية نجاح الصفقة.
      </p>
    </section>
  );
}
