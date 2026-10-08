import { Info } from 'lucide-react';

import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { timeframeLabel } from '@/features/analysis/lib/panelMetrics';
import { useSymbolMap } from '@/features/markets/queries';
import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/marketFormat';
import type { ChartContext } from '@/features/analysis/context/chartContext';
import type { ChartId } from '@/stores/layoutStore';
import type { AnalysisSnapshot } from '@/types/analysis';
import type { ExecutionState } from '@/types/execution';

import {
  BAND_AR,
  DECISION_STYLE,
  DECISION_TEXT,
  directionText,
  displayPlan,
  EXECUTION_AR,
  FAMILY_AR,
  LIFECYCLE_AR,
  MICRO_AR,
  REGIME_AR,
  TIMING_TEXT,
} from './model';

const FOCUS_OPTIONS = [
  { value: 'primary', label: 'الرئيسي' },
  { value: 'secondary', label: 'الثانوي' },
] as const satisfies readonly { value: ChartId; label: string }[];

const TONE: Record<string, string> = {
  bullish: 'text-bull',
  bearish: 'text-bear',
  neutral: 'text-fg',
};

function Row({
  label,
  value,
  tone,
  testId,
}: {
  label: string;
  value: string;
  tone?: string | undefined;
  testId?: string;
}) {
  return (
    <div className="flex min-w-0 items-baseline gap-1.5" data-testid={testId}>
      <dt className="text-fg-subtle shrink-0">{label}</dt>
      <dd dir="auto" className={cn('truncate font-semibold', tone ?? 'text-fg')} title={value}>
        {value}
      </dd>
    </div>
  );
}

function PlanCell({
  label,
  abbr,
  value,
  tone,
}: {
  label: string;
  abbr: string;
  value: string;
  tone?: string;
}) {
  return (
    <div
      data-plan={abbr}
      title={`${label}: ${value}`}
      className="bg-sunken border-line flex min-w-0 flex-col gap-1 rounded-lg border px-2.5 py-1.5"
    >
      <span className="text-fg-subtle text-2xs flex items-center gap-1.5 truncate">
        {label}
        <span className="ns-ltr text-fg-subtle/70 hidden @5xl:inline">{abbr}</span>
      </span>
      <span
        className={cn(
          'ns-num truncate font-medium',
          abbr === 'R:R' ? 'text-2xs @5xl:text-xs' : 'text-xs @5xl:text-sm',
          tone ?? 'text-fg',
        )}
      >
        {value}
      </span>
    </div>
  );
}

/**
 * Execution panel for 1m / 5m / 10m. Hierarchy: current decision -> entry timing -> trade
 * plan -> reasons -> supporting technical detail. Everything comes from the backend
 * execution layer; «قوة توقيت الدخول» is a timing score, never a win probability.
 */
export function ExecutionPanel({
  context,
  execution,
  snapshot,
  onFocus,
}: {
  context: ChartContext;
  execution: ExecutionState | null;
  snapshot: AnalysisSnapshot | null;
  onFocus: (chart: ChartId) => void;
}) {
  const symbols = useSymbolMap();
  const precision = symbols.get(context.symbol)?.price_precision;
  const p = (v: number) => formatPrice(String(v), precision);
  const ev = execution?.evaluation ?? null;
  const decision = ev?.decision ?? 'NO_SETUP';
  const plan = displayPlan(execution);
  const dir = directionText(execution);
  const parent = ev?.parent ?? null;
  const signal = execution?.signal ?? null;
  const confirmed = decision === 'BUY' || decision === 'SELL';
  const lifecycle = confirmed && signal ? signal.state : parent ? 'waiting' : null;
  const score = ev && parent ? Math.round(ev.score) : null;
  const regime = snapshot?.analysis_ready ? snapshot.regime?.primary : undefined;
  const ema = execution?.overlay?.ema;
  const micro = execution?.micro ?? ev?.micro ?? null;
  const support = execution?.overlay?.levels.find((l) => l.kind === 'support');
  const resistance = execution?.overlay?.levels.find((l) => l.kind === 'resistance');

  return (
    <section
      aria-label="لوحة توقيت الدخول"
      data-testid="execution-panel"
      data-decision={decision}
      className="ns-panel @container relative min-h-[275px] shrink-0 p-3 2xl:min-h-[345px]"
    >
      <header className="mb-2 flex items-center gap-2">
        <h2 className="text-sm font-semibold">{EXECUTION_AR.timing}</h2>
        <span
          data-testid="analysis-context"
          data-chart={context.chartId}
          className="ns-ltr text-fg-muted bg-sunken border-line rounded-md border px-1.5 text-xs"
        >
          {context.symbol} · {timeframeLabel(context.timeframe)}
        </span>
        <span className="text-fg-subtle text-2xs">
          {EXECUTION_AR.roleTitle[context.timeframe] ?? ''}
        </span>
        {parent && (
          <span className="text-fg-subtle text-2xs ns-ltr" data-testid="strategy-fingerprint">
            Strategy {parent.fingerprint}
          </span>
        )}
        {!execution && (
          <span role="status" className="text-fg-subtle text-2xs">
            {EXECUTION_AR.waiting}
          </span>
        )}
        <div className="ms-auto">
          <SegmentedControl
            size="sm"
            ariaLabel="الرسم الذي يصفه التحليل"
            value={context.chartId}
            options={FOCUS_OPTIONS}
            onChange={onFocus}
          />
        </div>
      </header>

      <div className="flex gap-3">
        <div
          data-testid="decision-summary"
          className="border-line flex w-48 shrink-0 flex-col gap-1.5 border-e pe-3 @5xl:w-60"
        >
          <div
            key={`${decision}|${context.symbol}|${context.timeframe}`}
            data-testid="signal-badge"
            data-decision={decision}
            className={cn(
              'ns-decision rounded-lg border px-2.5 py-1.5 text-center',
              DECISION_STYLE[decision],
            )}
          >
            <span className="block text-base leading-6 font-bold">{DECISION_TEXT[decision]}</span>
            <span
              data-testid="decision-headline"
              className="text-2xs block leading-4 font-medium opacity-80"
            >
              {ev?.headline ?? EXECUTION_AR.noSetup}
            </span>
          </div>
          <dl className="flex flex-col gap-0.5 text-xs">
            <Row
              label={EXECUTION_AR.direction}
              value={dir.label}
              tone={TONE[dir.tone]}
              testId="decision-direction"
            />
            <Row
              label={EXECUTION_AR.timing}
              value={TIMING_TEXT[decision]}
              testId="decision-timing"
            />
            {parent && (
              <Row
                label={EXECUTION_AR.parent}
                value={`${parent.timeframe} ${FAMILY_AR[parent.family] ?? parent.family}`}
                testId="decision-parent"
              />
            )}
            {lifecycle && (
              <Row label="الحالة" value={LIFECYCLE_AR[lifecycle]} testId="decision-lifecycle" />
            )}
          </dl>
          <div title={EXECUTION_AR.scoreHint} data-testid="strategy-score">
            <div className="text-fg-subtle text-2xs mb-1 flex items-center justify-between gap-2">
              <span className="flex items-center gap-1 truncate">
                {EXECUTION_AR.score}
                <Info className="size-3 shrink-0" aria-label={EXECUTION_AR.scoreHint} />
              </span>
              <span className="ns-num text-fg text-xs font-semibold" data-testid="signal-score">
                {score === null ? '--' : `${score.toString()} / 100`}
              </span>
            </div>
            <div
              className="bg-sunken border-line h-1.5 overflow-hidden rounded-full border"
              role="meter"
              aria-label={EXECUTION_AR.score}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={score ?? undefined}
            >
              {score !== null && (
                <span
                  className={cn(
                    'ns-meter block h-full',
                    decision === 'BUY'
                      ? 'bg-sig-buy'
                      : decision === 'SELL'
                        ? 'bg-sig-sell'
                        : 'bg-fg-subtle',
                  )}
                  style={{ width: `${String(score)}%` }}
                />
              )}
            </div>
            {ev?.score_band && parent && (
              <p className="text-fg-subtle text-2xs mt-0.5" data-testid="score-band">
                {BAND_AR[ev.score_band]}
              </p>
            )}
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          {plan && parent ? (
            <div
              className="grid grid-cols-6 gap-2"
              data-testid="trade-plan"
              data-preview={!confirmed}
            >
              <PlanCell label="الدخول" abbr="Entry" value={p(plan.entry)} />
              <PlanCell label="وقف الخسارة" abbr="SL" value={p(plan.stop)} tone="text-bear" />
              <PlanCell label="الهدف 1" abbr="TP1" value={p(plan.targets[0])} tone="text-bull" />
              <PlanCell label="الهدف 2" abbr="TP2" value={p(plan.targets[1])} tone="text-bull" />
              <PlanCell label="الهدف 3" abbr="TP3" value={p(plan.targets[2])} tone="text-bull" />
              <PlanCell
                label="R:R"
                abbr="R:R"
                value={plan.rr.map((r) => r.toFixed(1)).join(' / ')}
              />
            </div>
          ) : (
            <p
              className="bg-sunken/60 border-line text-fg-muted rounded-lg border px-2.5 py-2 text-xs"
              data-testid="no-setup"
            >
              {EXECUTION_AR.noSetup}
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <h3 className="text-xs font-semibold">{EXECUTION_AR.reasons}</h3>
              <ul
                className="text-fg-muted text-2xs mt-0.5 flex flex-col gap-0.5"
                data-testid="execution-reasons"
              >
                {(ev?.reasons ?? []).slice(0, 4).map((r) => (
                  <li key={r} className="flex min-w-0 items-baseline gap-1.5" title={r}>
                    <span aria-hidden className="bg-accent size-1 shrink-0 rounded-full" />
                    <span className="truncate">{r}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="text-xs font-semibold">{EXECUTION_AR.cautions}</h3>
              <ul
                className="text-fg-muted text-2xs mt-0.5 flex flex-col gap-0.5"
                data-testid="execution-cautions"
              >
                {(ev?.cautions ?? []).slice(0, 4).map((r) => (
                  <li key={r} className="flex min-w-0 items-baseline gap-1.5" title={r}>
                    <span aria-hidden className="bg-warning/80 size-1 shrink-0 rounded-full" />
                    <span className="truncate">{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <dl
            className="border-line text-2xs grid grid-cols-2 gap-x-4 gap-y-0.5 border-t pt-1.5 @5xl:grid-cols-4"
            data-testid="execution-technical"
          >
            <Row label="حالة السوق" value={regime ? (REGIME_AR[regime] ?? regime) : '--'} />
            <Row
              label="EMA 20/50/200"
              value={
                ema
                  ? [ema['20'], ema['50'], ema['200']]
                      .map((v) => (v === null ? '--' : p(v)))
                      .join(' / ')
                  : '--'
              }
            />
            <Row
              label="دعم / مقاومة"
              value={`${support ? `${p(support.price)} (${support.strength.toFixed(1)})` : '--'} / ${
                resistance ? `${p(resistance.price)} (${resistance.strength.toFixed(1)})` : '--'
              }`}
            />
            <Row
              label="بيانات لحظية"
              value={
                micro
                  ? `${MICRO_AR[micro.status] ?? micro.status}${
                      micro.spread_bp !== null ? ` · ${micro.spread_bp.toFixed(1)}bp` : ''
                    }`
                  : (MICRO_AR.unavailable ?? '')
              }
              testId="execution-micro"
            />
          </dl>
        </div>
      </div>

      <p className="text-fg-subtle text-2xs mt-2 flex items-center gap-1.5">
        <Info className="size-3" />
        {EXECUTION_AR.risk}
      </p>
    </section>
  );
}
