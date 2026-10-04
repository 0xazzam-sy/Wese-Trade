import { DIRECTION_AR, ALIGNMENT_AR } from '@/features/analysis/lib/labels';
import { directionTone, timeframeLabel } from '@/features/analysis/lib/panelMetrics';
import { cn } from '@/lib/cn';
import type { MtfFrame, MultiTimeframeContext } from '@/types/analysis';

const TONE_CLASS = {
  bull: 'text-bull',
  bear: 'text-bear',
  neutral: 'text-fg-muted',
  warning: 'text-warning',
  muted: 'text-fg-subtle',
} as const;

function Row({ frame, execution }: { frame: MtfFrame; execution?: boolean }) {
  const tone = frame.ready ? directionTone(frame.trend) : 'muted';
  return (
    <li className="flex items-center justify-between gap-2" data-mtf={frame.timeframe}>
      <span className={cn('ns-num text-2xs', execution ? 'text-accent' : 'text-fg-subtle')}>
        {timeframeLabel(frame.timeframe)}
      </span>
      <span className={cn('text-xs font-medium', TONE_CLASS[tone])}>
        {frame.ready && frame.trend ? DIRECTION_AR[frame.trend] : '--'}
      </span>
    </li>
  );
}

/** Higher-timeframe context (display only — never a signal). */
export function MtfPanel({ context }: { context: MultiTimeframeContext | null | undefined }) {
  return (
    <div aria-label="السياق متعدد الأطر" className="flex min-w-0 flex-col gap-1.5">
      <h3 className="text-fg-subtle text-2xs font-medium">الأطر الزمنية</h3>
      {context ? (
        <>
          <ul className="flex flex-col gap-1">
            <Row frame={context.execution} execution />
            {context.higher.map((frame) => (
              <Row key={frame.timeframe} frame={frame} />
            ))}
          </ul>
          <div className="border-line text-2xs mt-auto border-t pt-1.5">
            {context.higher.length === 0 ? (
              <span className="text-fg-subtle">لا يوجد إطار أعلى مدعوم بعد</span>
            ) : (
              <span className="text-fg-muted">{ALIGNMENT_AR[context.directional_alignment]}</span>
            )}
          </div>
        </>
      ) : (
        <span className="ns-num text-fg-subtle text-xs">--</span>
      )}
    </div>
  );
}
