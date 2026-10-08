import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/marketFormat';
import { ChartLegend } from '@/features/signals/chart/ChartLegend';
import type { ExecutionState } from '@/types/execution';

import { DECISION_STYLE, DECISION_TEXT, displayPlan, EXECUTION_AR } from './model';

function Value({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <span className="flex shrink-0 items-baseline gap-1 whitespace-nowrap">
      <span className="text-fg-subtle text-2xs">{label}</span>
      <span className={cn('ns-num font-semibold', tone ?? 'text-fg')}>{value}</span>
    </span>
  );
}

/**
 * Per-chart execution answer on 1m / 5m / 10m: decision (BUY / SELL / WAIT / ENTRY MISSED /
 * no setup) for the active Strategy 4.2 trade context, timing score and the plan.
 */
export function ExecutionStatus({
  state,
  precision,
}: {
  state: ExecutionState | null;
  precision?: number | undefined;
}) {
  const ev = state?.evaluation ?? null;
  const decision = ev?.decision ?? 'NO_SETUP';
  const plan = displayPlan(state);
  const p = (v: number) => formatPrice(String(v), precision);
  const trade = decision === 'BUY' || decision === 'SELL';

  return (
    <div
      data-testid="execution-status"
      data-decision={decision}
      role="status"
      aria-label={EXECUTION_AR.decisionTitle}
      className="border-line flex h-9 shrink-0 items-center gap-x-2.5 overflow-hidden border-b px-2.5 text-xs"
    >
      <span
        data-testid="execution-chip"
        className={cn(
          'shrink-0 rounded-md border px-2 py-0.5 text-xs font-bold',
          DECISION_STYLE[decision],
        )}
      >
        {DECISION_TEXT[decision]}
      </span>
      {ev?.parent && plan && (trade || decision === 'WAIT') ? (
        <>
          <Value label="الدخول" value={p(plan.entry)} />
          <Value label="الوقف" value={p(plan.stop)} tone="text-bear" />
          {plan.targets.map((t, i) => (
            <Value key={i} label={`TP${String(i + 1)}`} value={p(t)} tone="text-bull" />
          ))}
          <span
            className="flex shrink-0 items-baseline gap-1 whitespace-nowrap"
            title={EXECUTION_AR.scoreHint}
          >
            <span className="text-fg-subtle text-2xs">التوقيت</span>
            <span className="ns-num text-fg font-semibold" data-testid="execution-score">
              {Math.round(ev.score).toString()}/100
            </span>
          </span>
          <span className="text-fg-muted hidden min-w-0 truncate @4xl:inline">
            <span className="ns-ltr">{ev.parent.timeframe}</span> · {ev.headline}
          </span>
        </>
      ) : (
        <span className="text-fg-muted min-w-0 truncate" data-testid="execution-headline">
          {ev?.headline ?? EXECUTION_AR.noSetup}
        </span>
      )}
      <span className="ms-auto flex min-w-0 shrink items-center gap-2">
        <ChartLegend />
      </span>
    </div>
  );
}
