import { Bug, Info, ListTree } from 'lucide-react';
import { useState } from 'react';

import { IconButton } from '@/components/ui/IconButton';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { AnalysisDebug } from '@/features/analysis/components/AnalysisDebug';
import { ExecutionPanel } from '@/features/execution/ExecutionPanel';
import { isExecutionTimeframe } from '@/features/execution/model';
import { NOT_READY_AR } from '@/features/analysis/lib/labels';
import { timeframeLabel } from '@/features/analysis/lib/panelMetrics';
import { useSymbolMap } from '@/features/markets/queries';
import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/marketFormat';
import { useFocusedChartContext } from '@/features/analysis/context/chartContext';
import { useAnalysisStore } from '@/stores/analysisStore';
import type { ChartId } from '@/stores/layoutStore';
import type { AnalysisSnapshot } from '@/types/analysis';
import type { StrategyInfo, TradePlanDTO } from '@/types/signal';

import { CHART_SIGNAL_AR } from '@/features/signals/chart/copy';
import { BestOpportunity } from '@/features/strategy43/BestOpportunity';
import { TIER_STYLE } from '@/types/strategy43';

import { SignalDetails } from './components/SignalDetails';
import {
  explain,
  NO_ENTRY_TEXT,
  SCORE_LABEL,
  SCORE_TOOLTIP,
  type CategoryRow,
  type Decision,
  type ExplainTone,
} from './lib/explain';
import { formatScore, RISK_NOTE, SIGNAL_CLASS_STYLE } from './lib/labels';

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

/** Validation status of the strategy: never lets a signal look "proven" when it is not. */
function StrategyBadge({ strategy }: { strategy: StrategyInfo }) {
  const forward = strategy.forward_test || strategy.status === 'live';
  const fp = strategy.fingerprint ? ` · ${strategy.fingerprint}` : '';
  return (
    <span
      data-testid="strategy-status"
      data-status={strategy.status}
      title={`${strategy.name ?? 'Strategy'} (${strategy.version}${fp})`}
      className={cn(
        'text-2xs ms-auto truncate rounded-md border px-1.5 py-0.5 font-medium',
        forward
          ? 'border-accent/40 bg-accent/10 text-accent'
          : 'border-warning/40 bg-warning/10 text-warning',
      )}
    >
      {CHART_SIGNAL_AR.enabled}
    </span>
  );
}

/** Dot = does the category support or oppose the setup (not the market direction). */
const TONE_DOT: Record<ExplainTone, string> = {
  positive: 'bg-accent',
  negative: 'bg-warning',
  neutral: 'bg-fg-subtle/50',
};
const TONE_TITLE: Record<ExplainTone, string> = {
  positive: 'يدعم',
  negative: 'يعارض',
  neutral: 'محايد',
};
/** State text colored by the market direction it names. */
function stateColor(state: string): string {
  if (state.includes('صاعد')) return 'text-bull';
  if (state.includes('هابط')) return 'text-bear';
  return 'text-fg';
}
const DIRECTION_TEXT: Record<string, string> = {
  bullish: 'text-bull',
  bearish: 'text-bear',
  neutral: 'text-fg',
};

const DECISION_STYLE: Record<Decision, string> = {
  BUY: SIGNAL_CLASS_STYLE.BUY,
  SELL: SIGNAL_CLASS_STYLE.SELL,
  NEUTRAL: 'bg-neutral-soft text-fg border-line',
};

function CategoryCell({ row }: { row: CategoryRow }) {
  const pts =
    row.points === null
      ? null
      : row.max === null
        ? row.points.toString()
        : `${row.points.toString()}/${row.max.toString()}`;
  const ratio =
    row.points !== null && row.max ? Math.max(0, Math.min(1, row.points / row.max)) : null;
  return (
    <li
      data-category={row.key}
      data-tone={row.tone}
      title={`${row.label}: ${row.state} (${TONE_TITLE[row.tone]}) — ${row.explanation}`}
      className="ns-card-row flex min-w-0 flex-col gap-0.5 rounded-md px-2 py-1"
    >
      <div className="flex min-w-0 items-center gap-1.5 text-xs">
        <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', TONE_DOT[row.tone])} />
        <span className="text-fg-muted shrink-0">{row.label}</span>
        <span className={cn('min-w-0 truncate font-semibold', stateColor(row.state))}>
          {row.state}
        </span>
        {pts !== null && (
          <span className="ms-auto flex shrink-0 items-center gap-1">
            {ratio !== null && (
              <span className="bg-sunken border-line hidden h-1 w-8 overflow-hidden rounded-full border @5xl:block">
                <span
                  className={cn('block h-full', row.tone === 'negative' ? 'bg-bear' : 'bg-accent')}
                  style={{ width: `${String(Math.round(ratio * 100))}%` }}
                />
              </span>
            )}
            <span className="ns-num text-fg-subtle text-2xs" data-testid="category-points">
              {pts}
            </span>
          </span>
        )}
      </div>
      <p className="text-fg-subtle text-2xs hidden truncate @5xl:block">{row.explanation}</p>
    </li>
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
  const setFocused = useAnalysisStore((s) => s.setFocused);
  // Canonical context: never shows analysis of another symbol/timeframe than the chart.
  const { context, snapshot, view, execution } = useFocusedChartContext();
  const focused = context.chartId;
  const symbols = useSymbolMap();
  const [debugOpen, setDebugOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  if (isExecutionTimeframe(context.timeframe)) {
    return (
      <ExecutionPanel
        context={context}
        execution={execution}
        snapshot={snapshot}
        onFocus={setFocused}
      />
    );
  }
  const status = statusText(snapshot);
  const strategy = view?.strategy ?? null;
  const x = explain(snapshot, view, strategy);
  const display = x.display;
  const confirmed = x.decision === 'BUY' || x.decision === 'SELL';
  const plan = confirmed ? (display.signal?.plan ?? null) : null;
  const precision = symbols.get(context.symbol)?.price_precision;
  const values = planValues(plan, precision);
  const scoreValue = x.score === null ? 0 : Math.round(x.score);

  return (
    <section
      aria-label="لوحة التحليل"
      data-analysis-state={snapshot ? (snapshot.analysis_ready ? 'ready' : 'not-ready') : 'none'}
      data-signal-kind={display.kind}
      data-signal-class={display.signalClass}
      data-decision={x.decision}
      className="ns-panel @container relative min-h-[275px] shrink-0 p-3 2xl:min-h-[345px]"
    >
      {detailsOpen && (
        <SignalDetails
          signal={display.signal}
          evaluation={display.evaluation}
          mtf={snapshot?.analysis_ready ? snapshot.multi_timeframe : null}
          strategy={strategy}
          onClose={() => {
            setDetailsOpen(false);
          }}
        />
      )}
      <header className="mb-2 flex items-center gap-2">
        <h2 className="text-sm font-semibold">تحليل السوق</h2>
        <span
          data-testid="analysis-context"
          data-chart={context.chartId}
          className="ns-ltr text-fg-muted bg-sunken border-line rounded-md border px-1.5 text-xs"
        >
          {context.symbol} · {timeframeLabel(context.timeframe)}
        </span>
        {status && (
          <span role="status" className="text-fg-subtle text-2xs">
            {status}
          </span>
        )}
        {strategy && <StrategyBadge strategy={strategy} />}
        {strategy?.fingerprint && (
          <span className="text-fg-subtle text-2xs ns-ltr" data-testid="strategy-fingerprint">
            {strategy.fingerprint}
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
        {/* Decision summary: الاتجاه؟ هل في صفقة؟ ليش؟ */}
        <div
          data-testid="decision-summary"
          className="border-line flex w-48 shrink-0 flex-col gap-1.5 border-e pe-3 @5xl:w-60"
        >
          <div
            key={`${x.decision}|${context.symbol}|${context.timeframe}`}
            data-testid="signal-badge"
            data-decision={x.decision}
            className={cn(
              'ns-decision rounded-lg border px-2.5 py-1.5 text-center',
              DECISION_STYLE[x.decision],
            )}
          >
            <span className="block text-base leading-6 font-bold">{x.decisionLabel}</span>
            <span
              data-testid="decision-headline"
              className="text-2xs block leading-4 font-medium opacity-80"
            >
              {x.headline}
            </span>
          </div>
          {x.decision === 'NEUTRAL' && x.biasLabel && (
            <div
              data-testid="analysis-bias"
              data-bias={x.bias}
              title="ميل تحليلي من الاتجاه والهيكل — ليس إشارة تداول"
              className="border-line-strong flex items-center justify-between rounded-md border border-dashed px-2 py-0.5 text-xs"
            >
              <span className="text-fg-subtle">الميل التحليلي</span>
              <span className={cn('font-semibold', DIRECTION_TEXT[x.bias ?? 'neutral'])}>
                {x.biasLabel}
              </span>
            </div>
          )}
          <dl className="flex flex-col gap-0.5 text-xs">
            <div className="flex min-w-0 items-baseline gap-1.5" data-testid="decision-direction">
              <dt className="text-fg-subtle shrink-0">الاتجاه؟</dt>
              <dd
                title={x.direction.detail}
                className={cn(
                  'truncate font-semibold',
                  DIRECTION_TEXT[x.direction.tone ?? 'neutral'],
                )}
              >
                {x.direction.label}
              </dd>
            </div>
            <div className="flex min-w-0 items-baseline gap-1.5" data-testid="decision-trade">
              <dt className="text-fg-subtle shrink-0">هل في صفقة؟</dt>
              <dd className="truncate font-semibold" title={x.tradeLine}>
                {x.tradeLine}
              </dd>
            </div>
            {x.tier && x.tierLabel && (
              <div className="flex min-w-0 items-baseline gap-1.5" data-testid="signal-tier">
                <dt className="text-fg-subtle shrink-0">جودة الفرصة:</dt>
                <dd>
                  <span
                    data-tier={x.tier}
                    className={cn(
                      'rounded border px-1.5 text-xs font-semibold',
                      TIER_STYLE[x.tier],
                    )}
                  >
                    {x.tierLabel}
                  </span>
                </dd>
              </div>
            )}
            <div className="flex min-w-0 items-baseline gap-1.5" data-testid="signal-state">
              <dt className="text-fg-subtle shrink-0">ليش؟</dt>
              <dd
                className="text-fg-muted truncate @5xl:line-clamp-2 @5xl:whitespace-normal"
                title={x.reason}
              >
                {x.reason}
              </dd>
            </div>
          </dl>
          <div title={SCORE_TOOLTIP} data-testid="strategy-score">
            <div className="text-fg-subtle text-2xs mb-1 flex items-center justify-between gap-2">
              <span className="flex items-center gap-1 truncate">
                {SCORE_LABEL}
                <Info className="size-3 shrink-0" aria-label={SCORE_TOOLTIP} />
              </span>
              <span className="ns-num text-fg text-xs font-semibold" data-testid="signal-score">
                {formatScore(x.score)}
              </span>
            </div>
            <div
              className="bg-sunken border-line h-1.5 overflow-hidden rounded-full border"
              role="meter"
              aria-label={SCORE_LABEL}
              aria-description={SCORE_TOOLTIP}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={x.score === null ? undefined : scoreValue}
              aria-valuetext={x.score === null ? 'غير متاح' : formatScore(x.score)}
            >
              {x.score !== null && (
                <span
                  className={cn(
                    'ns-meter block h-full',
                    x.decision === 'BUY'
                      ? 'bg-sig-buy'
                      : x.decision === 'SELL'
                        ? 'bg-sig-sell'
                        : 'bg-fg-subtle',
                  )}
                  style={{ width: `${String(scoreValue)}%` }}
                />
              )}
            </div>
            {x.candidateScore && (
              <p className="text-fg-subtle text-2xs mt-0.5" data-testid="candidate-score">
                أفضل إعداد مرشّح — لم يستوفِ شروط الإشارة
              </p>
            )}
            {strategy?.score_calibrated === false && (
              <span data-testid="score-uncalibrated" className="sr-only">
                غير معايرة
              </span>
            )}
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          {confirmed ? (
            <div className="grid grid-cols-6 gap-2" data-testid="trade-plan">
              {PLAN_METRICS.map((m, i) => (
                <PlanCell key={m.label} metric={m} value={values[i] ?? null} developing={false} />
              ))}
            </div>
          ) : (
            <div
              data-testid="entry-blockers"
              title={x.blockers.join('\n')}
              className="bg-sunken/60 border-line rounded-lg border px-2.5 py-1"
            >
              <h3 className="text-xs font-semibold" data-testid="no-trade-line">
                {strategy?.signal_capable ? NO_ENTRY_TEXT : 'ما الذي يمنع الدخول حالياً؟'}
              </h3>
              {strategy?.signal_capable && (
                <BestOpportunity best={view?.best} timeframe={context.timeframe} />
              )}
              {x.blockers.length > 0 ? (
                <ul className="text-fg-muted text-2xs mt-0.5 grid grid-cols-2 gap-x-4 gap-y-0.5">
                  {x.blockers.slice(0, 4).map((b) => (
                    <li key={b} className="flex min-w-0 items-baseline gap-1.5" title={b}>
                      <span aria-hidden className="bg-bear/70 size-1 shrink-0 rounded-full" />
                      <span className="truncate">{b}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-fg-subtle text-2xs mt-1">لا توجد بيانات تقييم بعد.</p>
              )}
            </div>
          )}
          <ul
            aria-label="شرح التحليل"
            className="ns-scroll grid grid-cols-3 gap-x-1 gap-y-0.5 @5xl:max-h-52 @5xl:overflow-y-auto"
          >
            {x.categories.map((row) => (
              <CategoryCell key={row.key} row={row} />
            ))}
          </ul>
        </div>
      </div>

      <p className="text-fg-subtle text-2xs mt-2 flex items-center gap-1.5">
        <Info className="size-3" />
        {RISK_NOTE} {SCORE_TOOLTIP}
      </p>
      {import.meta.env.DEV && debugOpen && <AnalysisDebug snapshot={snapshot} />}
    </section>
  );
}
