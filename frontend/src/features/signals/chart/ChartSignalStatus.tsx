import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/marketFormat';
import type { SignalDTO, StrategyInfo } from '@/types/signal';

import { FAMILY_AR, formatScore } from '../lib/labels';
import { chartSignalState, type ChartSignalState } from './chartSignals';
import { ChartLegend } from './ChartLegend';
import { CHART_SIGNAL_AR } from './copy';

const CHIP: Record<ChartSignalState, { text: string; className: string }> = {
  buy: { text: CHART_SIGNAL_AR.buy, className: 'bg-bull/15 text-bull border-bull/50' },
  sell: { text: CHART_SIGNAL_AR.sell, className: 'bg-bear/15 text-bear border-bear/50' },
  neutral: { text: CHART_SIGNAL_AR.neutral, className: 'bg-sig-neutral/10 text-fg border-line' },
  research: {
    text: CHART_SIGNAL_AR.researchOnly,
    className: 'bg-warning/10 text-warning border-warning/40',
  },
  paused: { text: CHART_SIGNAL_AR.neutral, className: 'bg-sig-neutral/10 text-fg border-line' },
};

function Value({
  label,
  short,
  value,
  tone,
}: {
  label: string;
  /** Label used when the chart panel is narrow. */
  short?: string;
  value: string;
  tone?: string;
}) {
  return (
    <span className="flex shrink-0 items-baseline gap-1 whitespace-nowrap">
      <span className="text-fg-subtle text-2xs">
        {short ? (
          <>
            <span className="@4xl:hidden">{short}</span>
            <span className="hidden @4xl:inline">{label}</span>
          </>
        ) : (
          label
        )}
      </span>
      <span className={cn('ns-num font-semibold', tone ?? 'text-fg')}>{value}</span>
    </span>
  );
}

/**
 * Per-chart answer to «شو موقف النظام هلق؟». BUY/SELL only from a confirmed open
 * forward-test signal of THIS chart; otherwise neutral (or analysis-only timeframe).
 */
export function ChartSignalStatus({
  timeframe,
  open,
  strategy,
  precision,
}: {
  timeframe: string;
  open: SignalDTO | null;
  strategy: StrategyInfo | null;
  precision?: number | undefined;
}) {
  const state = chartSignalState(timeframe, open, strategy);
  const chip = CHIP[state];
  const p = (v: number) => formatPrice(String(v), precision);
  const signal = state === 'buy' || state === 'sell' ? open : null;

  return (
    <div
      data-testid="chart-signal-status"
      data-state={state}
      role="status"
      aria-label={CHART_SIGNAL_AR.question}
      title={CHART_SIGNAL_AR.question}
      className="border-line flex h-9 shrink-0 items-center gap-x-2.5 overflow-hidden border-b px-2.5 text-xs"
    >
      <span
        data-testid="chart-signal-chip"
        className={cn('shrink-0 rounded-md border px-2 py-0.5 text-xs font-bold', chip.className)}
      >
        {chip.text}
      </span>

      {signal ? (
        <>
          <Value label="الدخول" value={p(signal.entry_price ?? signal.plan.preferred_entry)} />
          <Value label="وقف الخسارة" short="الوقف" value={p(signal.plan.stop)} tone="text-bear" />
          {signal.plan.targets.map((t, i) => (
            <Value key={i} label={`TP${String(i + 1)}`} value={p(t.price)} tone="text-bull" />
          ))}
          <span
            className="flex shrink-0 items-baseline gap-1 whitespace-nowrap"
            title={`قوة الإشارة ${formatScore(signal.score)} — ${CHART_SIGNAL_AR.uncalibrated}`}
          >
            <span className="text-fg-subtle text-2xs">
              <span className="@4xl:hidden">القوة</span>
              <span className="hidden @4xl:inline">قوة الإشارة</span>
            </span>
            <span className="ns-num text-fg font-semibold">{formatScore(signal.score)}</span>
            <span className="text-fg-subtle text-2xs hidden @5xl:inline">
              ({CHART_SIGNAL_AR.uncalibrated})
            </span>
          </span>
          <span
            data-testid="chart-signal-family"
            className="text-fg-muted hidden shrink-0 whitespace-nowrap @4xl:inline"
          >
            <span className="ns-ltr">{signal.timeframe}</span> · {FAMILY_AR[signal.family]}
          </span>
        </>
      ) : (
        <span className="text-fg-muted min-w-0 truncate">
          {state === 'research'
            ? CHART_SIGNAL_AR.researchOnlyDetail
            : state === 'paused'
              ? CHART_SIGNAL_AR.paused
              : CHART_SIGNAL_AR.neutralDetail}
        </span>
      )}

      <span className="ms-auto flex min-w-0 shrink items-center gap-2">
        {state !== 'research' && (
          <span
            data-testid="chart-signal-scope"
            className={cn(
              'text-fg-subtle text-2xs min-w-0 truncate',
              signal && 'hidden @5xl:block',
            )}
            title={`${CHART_SIGNAL_AR.forward} · ${CHART_SIGNAL_AR.unproven} — ${CHART_SIGNAL_AR.disclaimer}`}
          >
            {signal
              ? `${CHART_SIGNAL_AR.unproven} — ${CHART_SIGNAL_AR.disclaimer}`
              : `${CHART_SIGNAL_AR.enabled} · ${CHART_SIGNAL_AR.forward} · ${CHART_SIGNAL_AR.unproven}`}
          </span>
        )}
        <ChartLegend />
      </span>
    </div>
  );
}
