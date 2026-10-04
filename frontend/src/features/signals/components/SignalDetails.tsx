import { X } from 'lucide-react';

import { ALIGNMENT_AR } from '@/features/analysis/lib/labels';
import { timeframeLabel } from '@/features/analysis/lib/panelMetrics';
import { cn } from '@/lib/cn';
import type { MultiTimeframeContext } from '@/types/analysis';
import type { ComponentDTO, SignalDTO, SignalEvaluationDTO } from '@/types/signal';

import {
  COMPONENT_AR,
  FAMILY_AR,
  formatScore,
  RISK_NOTE,
  SIGNAL_CLASS_AR,
  STATE_AR,
} from '../lib/labels';

interface Props {
  signal: SignalDTO | null;
  evaluation: SignalEvaluationDTO | null;
  mtf: MultiTimeframeContext | null | undefined;
  onClose: () => void;
}

function Components({ items }: { items: ComponentDTO[] }) {
  return (
    <ul className="flex flex-col gap-1">
      {items.map((c) => (
        <li key={c.name} className="flex items-center gap-2 text-xs">
          <span className="text-fg-muted w-28 shrink-0 truncate">
            {COMPONENT_AR[c.name] ?? c.name}
          </span>
          <span className="bg-sunken h-1.5 flex-1 overflow-hidden rounded-full">
            <span
              className="bg-accent block h-full"
              style={{ width: `${String(Math.round(c.value * 100))}%` }}
            />
          </span>
          <span className="ns-num text-fg-subtle w-14 text-end">
            {c.points.toFixed(1)}/{c.weight.toFixed(0)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Compact details drawer: why the engine said what it said. Display only. */
export function SignalDetails({ signal, evaluation, mtf, onClose }: Props) {
  const hyp = evaluation?.hypothesis ?? null;
  const family = signal?.family ?? hyp?.family;
  const signalClass = signal?.signal_class ?? evaluation?.signal_class ?? 'NEUTRAL';
  const score = signal?.score ?? (signalClass === 'NEUTRAL' ? null : (evaluation?.score ?? null));
  const positive = signal?.positive ?? hyp?.positive ?? [];
  const negative = [
    ...(signal?.negative ?? hyp?.negative ?? []),
    ...(signalClass === 'NEUTRAL' && evaluation?.neutral_reason ? [evaluation.neutral_reason] : []),
  ];
  const components = signal?.components ?? hyp?.components ?? [];
  const created = signal ? new Date(signal.confirmed_time * 1000).toLocaleString() : null;
  return (
    <aside
      role="dialog"
      aria-label="تفاصيل الإشارة"
      className="bg-surface-strong border-line shadow-pop absolute inset-x-3 bottom-full z-40 mb-2 max-h-[60vh] overflow-auto rounded-xl border p-3"
    >
      <header className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold">تفاصيل الإشارة</h3>
        <button
          type="button"
          aria-label="إغلاق التفاصيل"
          onClick={onClose}
          className="text-fg-muted hover:text-fg ms-auto"
        >
          <X className="size-4" />
        </button>
      </header>
      <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs @5xl:grid-cols-4">
        <dt className="text-fg-subtle">نوع الإعداد</dt>
        <dd>{family ? FAMILY_AR[family] : '--'}</dd>
        <dt className="text-fg-subtle">الإشارة</dt>
        <dd>{SIGNAL_CLASS_AR[signalClass]}</dd>
        <dt className="text-fg-subtle">قوة الإشارة</dt>
        <dd className="ns-num" data-testid="details-score">
          {formatScore(score)}
        </dd>
        <dt className="text-fg-subtle">حالة الإشارة</dt>
        <dd>
          {signal ? STATE_AR[signal.state] : evaluation?.developing ? STATE_AR.developing : '--'}
        </dd>
        <dt className="text-fg-subtle">وقت الإنشاء</dt>
        <dd className="ns-num">{created ?? '--'}</dd>
        <dt className="text-fg-subtle">السياق متعدد الفريمات</dt>
        <dd>
          {mtf
            ? `${ALIGNMENT_AR[mtf.directional_alignment]} (${mtf.higher.map((f) => timeframeLabel(f.timeframe)).join('، ') || '—'})`
            : '--'}
        </dd>
      </dl>
      <div className="grid gap-3 @5xl:grid-cols-3">
        <section aria-label="مكونات الدرجة">
          <h4 className="text-fg-subtle text-2xs mb-1">مكونات الدرجة (توافق، ليست احتمالية)</h4>
          {components.length ? (
            <Components items={components} />
          ) : (
            <p className="text-fg-subtle text-xs">--</p>
          )}
        </section>
        <section aria-label="عوامل داعمة">
          <h4 className="text-fg-subtle text-2xs mb-1">عوامل داعمة</h4>
          <ul className="flex flex-col gap-0.5 text-xs">
            {positive.length ? (
              positive.map((r) => (
                <li key={r} className="text-bull">
                  + {r}
                </li>
              ))
            ) : (
              <li className="text-fg-subtle">--</li>
            )}
          </ul>
        </section>
        <section aria-label="عوامل معاكسة">
          <h4 className="text-fg-subtle text-2xs mb-1">عوامل معاكسة</h4>
          <ul className="flex flex-col gap-0.5 text-xs">
            {negative.length ? (
              negative.map((r) => (
                <li key={r} className="text-bear">
                  − {r}
                </li>
              ))
            ) : (
              <li className="text-fg-subtle">--</li>
            )}
          </ul>
        </section>
      </div>
      <p className={cn('text-fg-subtle text-2xs mt-3')}>
        {RISK_NOTE} الإصدار:{' '}
        <span className="ns-ltr">
          {signal?.strategy_version ?? evaluation?.strategy_version ?? '--'}
        </span>
      </p>
    </aside>
  );
}
