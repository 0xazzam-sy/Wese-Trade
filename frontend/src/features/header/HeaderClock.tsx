import { useNow } from '@/hooks/useNow';
import { formatClockTime, formatLongDate, timeZoneLabel } from '@/lib/format';

/** Browser/user timezone clock with seconds. No timezone is hardcoded. */
export function HeaderClock() {
  const now = useNow();

  return (
    <div className="flex items-center gap-3" aria-label="التاريخ والوقت">
      <span className="text-fg-muted text-xs">{formatLongDate(now)}</span>
      <span className="bg-line h-4 w-px" aria-hidden />
      <time
        dateTime={now.toISOString()}
        className="ns-num text-fg text-sm font-medium"
        suppressHydrationWarning
      >
        {formatClockTime(now)}
      </time>
      <span className="ns-ltr text-fg-subtle text-2xs">{timeZoneLabel(now)}</span>
    </div>
  );
}
