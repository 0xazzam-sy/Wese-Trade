import { Activity, Bug, Info, ListTree } from 'lucide-react';
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
import { useSymbolMap } from '@/features/markets/queries';
import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/marketFormat';
import { useAnalysisStore } from '@/stores/analysisStore';
import type { ChartId } from '@/stores/layoutStore';
import type { AnalysisSnapshot } from '@/types/analysis';
import type { TradePlanDTO } from '@/types/signal';

import { SignalDetails } from './components/SignalDetails';
import { signalDisplay, type SignalDisplay } from './lib/display';
import {
  formatScore,
  RISK_NOTE,
  SIGNAL_CLASS_AR,
  SIGNAL_CLASS_STYLE,
  STATE_AR,
} from './lib/labels';

interface Metric {
  label: string;
  /** Shorter Arabic label used when the panel is narrow (e.g. 1366px screens). */
  short?: string;
  /** Latin financial abbreviation shown next to the Arabic label. */
  abbr?: string;
}

const PLAN_METRICS: Metric[] = [
  { label: 'سعر الدخول', short: 'الدخول', abbr: 'Entry' },
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

function planValues(plan: TradePlanDTO | null, precision?: number): (string | null)[] {
  if (!plan) return PLAN_METRICS.map(() => null);
  const p = (v: number) => formatPrice(String(v), precision);
  const entry =
    plan.entry_model === 'ZONE_ENTRY' && plan.entry_low !== plan.entry_high
      ? `${p(plan.entry_low)} – ${p(plan.entry_high)}`
      : p(plan.preferred_entry);
  const [t1, t2, t3] = plan.targets;
  const rr = plan.targets.map((t) => t.rr.toFixed(1)).join(' / ');
  return [entry, p(plan.stop), p(t1.price), p(t2.price), p(t3.price), rr];
}

function PlanCell({
  metric,
  value,
  developing,
}: {
  metric: Metric;
  value: string | null;
  developing: boolean;
}) {
  return (
    <div
      data-plan={metric.abbr}
      title={value ? `${metric.label}: ${value}` : `${metric.label} — لا توجد إشارة`}
      className={cn(
        'bg-sunken border-line flex min-w-0 flex-col gap-1 rounded-lg border px-2.5 py-1.5',
        developing && 'border-dashed opacity-70',
      )}
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
      <span
        className={cn(
          'ns-num truncate text-sm font-medium',
          value ? 'text-fg' : 'text-fg-muted',
          metric.abbr === 'SL' && value && 'text-bear',
        )}
      >
        {value ?? EMPTY_VALUE}
      </span>
    </div>
  );
}

function signalLabel(d: SignalDisplay): string {
  if (d.kind === 'none') return 'لا توجد إشارة حالياً';
  const name = SIGNAL_CLASS_AR[d.signalClass];
  return d.kind === 'developing' ? `${name} — قيد التشكّل` : name;
}

function stateLine(d: SignalDisplay): string | null {
  if (d.signal) return STATE_AR[d.signal.state];
  if (d.kind === 'developing') return 'فرضية على شمعة لم تُغلق بعد — ليست إشارة مؤكدة';
  if (d.kind === 'evaluation' && d.signalClass === 'NEUTRAL') return d.neutralReason;
  return null;
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
 * Signal + analysis panel. Every value is computed by the backend (analysis engine and
 * signal engine); React only formats it. «قوة الإشارة» is a confluence score out of 100,
 * never a probability of profit.
 */
export function SignalPanel() {
  const focused = useAnalysisStore((s) => s.focused);
  const setFocused = useAnalysisStore((s) => s.setFocused);
  const snapshot = useAnalysisStore((s) => s.byChart[s.focused]);
  const view = useAnalysisStore((s) => s.signals[s.focused]);
  const symbols = useSymbolMap();
  const [debugOpen, setDebugOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const metrics = panelMetrics(snapshot);
  const status = statusText(snapshot);
  const display = signalDisplay(view);
  const developing = display.kind === 'developing';
  const plan = display.signal?.plan ?? (developing ? (display.evaluation?.plan ?? null) : null);
  const precision = snapshot ? symbols.get(snapshot.symbol)?.price_precision : undefined;
  const values = planValues(plan, precision);
  const state = stateLine(display);
  const scoreValue = display.score === null ? 0 : Math.round(display.score);

  return (
    <section
      aria-label="لوحة التحليل"
      data-analysis-state={snapshot ? (snapshot.analysis_ready ? 'ready' : 'not-ready') : 'none'}
      data-signal-kind={display.kind}
      data-signal-class={display.signalClass}
      className="ns-panel @container relative shrink-0 p-3"
    >
      {detailsOpen && (
        <SignalDetails
          signal={display.signal}
          evaluation={display.evaluation}
          mtf={snapshot?.analysis_ready ? snapshot.multi_timeframe : null}
          onClose={() => {
            setDetailsOpen(false);
          }}
        />
      )}
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
          <IconButton
            size="sm"
            label="تفاصيل الإشارة"
            active={detailsOpen}
            disabled={display.kind === 'none'}
            onClick={() => {
              setDetailsOpen((v) => !v);
            }}
            icon={<ListTree className="size-3.5" />}
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
          <div
            data-testid="signal-badge"
            className={cn(
              'rounded-lg border px-3 py-2 text-center text-sm font-semibold',
              display.kind === 'none'
                ? 'bg-neutral-soft text-fg-muted border-transparent font-medium'
                : SIGNAL_CLASS_STYLE[display.signalClass],
              developing && 'animate-pulse border-dashed border-warning/60',
            )}
          >
            {signalLabel(display)}
          </div>
          <div>
            <div className="text-fg-subtle text-2xs mb-1 flex items-center justify-between">
              <span>قوة الإشارة</span>
              <span className="ns-num" data-testid="signal-score">
                {formatScore(display.score)}
              </span>
            </div>
            <div
              className="bg-sunken border-line h-1.5 overflow-hidden rounded-full border"
              role="meter"
              aria-label="قوة الإشارة"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={display.score === null ? undefined : scoreValue}
              aria-valuetext={display.score === null ? 'غير متاح' : formatScore(display.score)}
            >
              {display.score !== null && (
                <span
                  className={cn(
                    'block h-full',
                    developing ? 'bg-warning' : 'bg-current',
                    !developing && SIGNAL_CLASS_STYLE[display.signalClass].split(' ')[1],
                  )}
                  style={{ width: `${String(scoreValue)}%` }}
                />
              )}
            </div>
          </div>
          {state && (
            <p className="text-fg-subtle text-2xs line-clamp-2" data-testid="signal-state">
              {state}
            </p>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="grid grid-cols-6 gap-2">
            {PLAN_METRICS.map((m, i) => (
              <PlanCell
                key={m.label}
                metric={m}
                value={values[i] ?? null}
                developing={developing}
              />
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
        {RISK_NOTE} قوة الإشارة درجة توافق شروط الاستراتيجية، وليست احتمالية نجاح الصفقة.
      </p>
      {import.meta.env.DEV && debugOpen && <AnalysisDebug snapshot={snapshot} />}
    </section>
  );
}
