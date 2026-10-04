import { Activity, Bug, Info } from 'lucide-react';
import { useState } from 'react';

import { IconButton } from '@/components/ui/IconButton';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { AnalysisDebug } from '@/features/analysis/components/AnalysisDebug';
import { MtfPanel } from '@/features/analysis/components/MtfPanel';
import { NOT_READY_AR } from '@/features/analysis/lib/labels';
import {
  panelMetrics,
  timeframeLabel,
  type PanelMetric,
  type Tone,
} from '@/features/analysis/lib/panelMetrics';
import { cn } from '@/lib/cn';
import { useAnalysisStore } from '@/stores/analysisStore';
import type { ChartId } from '@/stores/layoutStore';
import type { AnalysisSnapshot } from '@/types/analysis';

interface Metric {
  label: string;
  /** Shorter Arabic label used when the panel is narrow (e.g. 1366px screens). */
  short?: string;
  /** Latin financial abbreviation shown next to the Arabic label. */
  abbr?: string;
}

/** Trade-plan fields belong to the future signal engine (phase 4): always "--" here. */
const PLAN_METRICS: Metric[] = [
  { label: 'سعر الدخول', abbr: 'Entry' },
  { label: 'وقف الخسارة', abbr: 'SL' },
  { label: 'الهدف الأول', abbr: 'TP1' },
  { label: 'الهدف الثاني', abbr: 'TP2' },
  { label: 'الهدف الثالث', abbr: 'TP3' },
  { label: 'نسبة المخاطرة إلى العائد', short: 'المخاطرة/العائد', abbr: 'R:R' },
];

const EMPTY_VALUE = '--';

const TONE_CLASS: Record<Tone, string> = {
  bull: 'text-bull',
  bear: 'text-bear',
  neutral: 'text-fg',
  warning: 'text-warning',
  muted: 'text-fg-muted',
};

const FOCUS_OPTIONS = [
  { value: 'primary', label: 'الرئيسي' },
  { value: 'secondary', label: 'الثانوي' },
] as const satisfies readonly { value: ChartId; label: string }[];

function PlanCell({ metric }: { metric: Metric }) {
  return (
    <div
      title={`${metric.label} — غير متاح بعد`}
      className="bg-sunken border-line flex min-w-0 flex-col gap-1 rounded-lg border px-2.5 py-1.5"
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

function AnalysisCell({ metric }: { metric: PanelMetric }) {
  return (
    <div
      data-metric={metric.key}
      title={metric.detail ? `${metric.value} — ${metric.detail}` : metric.value}
      className="bg-sunken border-line flex min-w-0 flex-col gap-0.5 rounded-lg border px-2.5 py-1.5"
    >
      <span className="text-fg-subtle text-2xs truncate">{metric.label}</span>
      <span className={cn('truncate text-xs font-semibold', TONE_CLASS[metric.tone])}>
        {metric.value}
      </span>
      <span className="text-fg-subtle text-2xs ns-num truncate">{metric.detail ?? ' '}</span>
    </div>
  );
}

function statusText(snapshot: AnalysisSnapshot | null): string | null {
  if (!snapshot) return NOT_READY_AR.loading_history ?? null;
  if (!snapshot.analysis_ready) {
    return NOT_READY_AR[snapshot.reason ?? ''] ?? 'التحليل غير متاح';
  }
  return null;
}

/**
 * Analysis panel. Every value is computed by the backend analysis engine; React only
 * formats it. Signal label, strength and the trade plan (Entry/SL/TP/R:R) belong to the
 * future signal engine and stay "--" in this phase.
 */
export function SignalPanel() {
  const focused = useAnalysisStore((s) => s.focused);
  const setFocused = useAnalysisStore((s) => s.setFocused);
  const snapshot = useAnalysisStore((s) => s.byChart[s.focused]);
  const [debugOpen, setDebugOpen] = useState(false);
  const metrics = panelMetrics(snapshot);
  const status = statusText(snapshot);

  return (
    <section
      aria-label="لوحة التحليل"
      data-analysis-state={snapshot ? (snapshot.analysis_ready ? 'ready' : 'not-ready') : 'none'}
      className="ns-panel @container shrink-0 p-3"
    >
      <header className="mb-2 flex items-center gap-2">
        <h2 className="text-sm font-semibold">تحليل السوق</h2>
        {snapshot && (
          <span className="ns-ltr text-fg-muted bg-sunken border-line rounded-md border px-1.5 text-xs">
            {snapshot.symbol} · {timeframeLabel(snapshot.timeframe)}
          </span>
        )}
        {status && (
          <span role="status" className="text-fg-subtle text-2xs">
            {status}
          </span>
        )}
        <div className="ms-auto flex items-center gap-1.5">
          <SegmentedControl
            size="sm"
            ariaLabel="الرسم الذي يصفه التحليل"
            value={focused}
            options={FOCUS_OPTIONS}
            onChange={setFocused}
          />
          {import.meta.env.DEV && (
            <IconButton
              size="sm"
              label="عرض بيانات التطوير"
              active={debugOpen}
              onClick={() => {
                setDebugOpen((v) => !v);
              }}
              icon={<Bug className="size-3.5" />}
            />
          )}
        </div>
      </header>

      <div className="flex gap-3">
        <div className="border-line flex w-40 shrink-0 flex-col gap-2 border-e pe-3 @5xl:w-52">
          <div className="flex items-center gap-2">
            <Activity className="text-accent size-4" />
            <h3 className="text-sm font-semibold">الإشارة</h3>
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

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="grid grid-cols-6 gap-2">
            {PLAN_METRICS.map((m) => (
              <PlanCell key={m.label} metric={m} />
            ))}
          </div>
          <div className="grid grid-cols-5 gap-2 @5xl:grid-cols-9" aria-label="مؤشرات التحليل">
            {metrics.map((m) => (
              <AnalysisCell key={m.key} metric={m} />
            ))}
          </div>
        </div>

        <div className="border-line w-28 shrink-0 border-s ps-3 @5xl:w-36">
          <MtfPanel context={snapshot?.analysis_ready ? snapshot.multi_timeframe : null} />
        </div>
      </div>

      <p className="text-fg-subtle text-2xs mt-2 flex items-center gap-1.5">
        <Info className="size-3" />
        التحليل وصف لحالة السوق وليس توصية. قوة الإشارة ستمثل درجة توافق شروط الاستراتيجية، وليست
        احتمالية نجاح الصفقة.
      </p>
      {import.meta.env.DEV && debugOpen && <AnalysisDebug snapshot={snapshot} />}
    </section>
  );
}
