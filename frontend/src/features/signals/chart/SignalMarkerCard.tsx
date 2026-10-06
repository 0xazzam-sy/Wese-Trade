import { createPortal } from 'react-dom';

import { cn } from '@/lib/cn';
import { formatPrice } from '@/lib/marketFormat';
import type { SignalDTO } from '@/types/signal';

import { formatScore, STATE_AR } from '../lib/labels';
import { isOpenSignal } from './chartSignals';
import { CHART_SIGNAL_AR, fingerprintOf, formatSignalTime } from './copy';

const CARD_WIDTH = 300;
const CARD_HEIGHT = 290;

/** Details of one BUY/SELL marker (hover or click). Display only: values come from the engine. */
export function SignalMarkerCard({
  signal,
  x,
  y,
  precision,
}: {
  signal: SignalDTO;
  /** Pointer position in viewport coordinates. */
  x: number;
  y: number;
  precision?: number | undefined;
}) {
  const p = (v: number) => formatPrice(String(v), precision);
  const long = signal.side === 'long';
  const open = isOpenSignal(signal);
  // Fixed position, kept inside the window (never clipped by a short chart panel).
  const left = x + 16 + CARD_WIDTH < window.innerWidth ? x + 16 : Math.max(4, x - 16 - CARD_WIDTH);
  const top = Math.max(4, Math.min(y - 40, window.innerHeight - CARD_HEIGHT - 4));
  // [label, value, tone, full width]
  const rows: [string, string, (string | undefined)?, boolean?][] = [
    ['نوع الإشارة', long ? 'شراء BUY' : 'بيع SELL', long ? 'text-bull' : 'text-bear', true],
    ['الحالة', `${CHART_SIGNAL_AR.forward} · ${STATE_AR[signal.state]}`, undefined, true],
    ['الوقت', formatSignalTime(signal.trigger_time), undefined, true],
    ['الرمز', signal.symbol],
    ['الفريم', signal.timeframe],
    [
      'قوة الإشارة',
      `${formatScore(signal.score)} · ${CHART_SIGNAL_AR.uncalibrated}`,
      undefined,
      true,
    ],
    ['الاستراتيجية', CHART_SIGNAL_AR.strategyName],
    ['Entry', p(signal.entry_price ?? signal.plan.preferred_entry)],
    ['Stop Loss', p(signal.plan.stop), 'text-bear'],
    ...signal.plan.targets.map(
      (t, i) => [`TP${String(i + 1)}`, p(t.price), 'text-bull'] as [string, string, string],
    ),
    ['Risk/Reward', signal.plan.rr.map((r) => r.toFixed(2)).join(' / ')],
    ['Strategy fingerprint', fingerprintOf(signal.strategy_version)],
  ];

  // Portal: a panel's backdrop-filter would otherwise trap (and clip) the fixed card.
  return createPortal(
    <div
      data-testid="signal-marker-card"
      data-signal={signal.id}
      data-open={open}
      dir="rtl"
      style={{ left, top, width: CARD_WIDTH }}
      className="bg-surface-strong/95 border-line shadow-pop pointer-events-none fixed z-40 rounded-lg border p-2.5 text-xs backdrop-blur"
    >
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
        {rows.map(([label, value, tone, wide]) => (
          <div key={label} className={cn('min-w-0', wide && 'col-span-2')}>
            <dt className="text-fg-subtle text-2xs truncate">{label}</dt>
            <dd className={cn('ns-num truncate font-medium', tone ?? 'text-fg')}>{value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-fg-subtle text-2xs border-line mt-2 border-t pt-1.5">
        {CHART_SIGNAL_AR.unproven} — {CHART_SIGNAL_AR.disclaimer}
      </p>
    </div>,
    document.body,
  );
}
