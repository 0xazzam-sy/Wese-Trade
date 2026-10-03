import { type Time, TickMarkType } from 'lightweight-charts';

/**
 * Candle times are UTC epoch seconds internally. lightweight-charts renders them as UTC,
 * so these formatters convert to the browser/user timezone for display only.
 */
const LOCALE = 'en-GB'; // Latin digits, 24h; axis labels stay compact and LTR.

const fmt = {
  year: new Intl.DateTimeFormat(LOCALE, { year: 'numeric' }),
  month: new Intl.DateTimeFormat(LOCALE, { month: 'short', year: '2-digit' }),
  day: new Intl.DateTimeFormat(LOCALE, { day: '2-digit', month: 'short' }),
  time: new Intl.DateTimeFormat(LOCALE, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }),
  seconds: new Intl.DateTimeFormat(LOCALE, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }),
  full: new Intl.DateTimeFormat(LOCALE, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }),
};

function toDate(time: Time): Date | null {
  return typeof time === 'number' ? new Date(time * 1000) : null;
}

export const chartLocalization = {
  timeFormatter: (time: Time): string => {
    const date = toDate(time);
    return date ? fmt.full.format(date) : '';
  },
  tickMarkFormatter: (time: Time, type: TickMarkType): string | null => {
    const date = toDate(time);
    if (!date) return null;
    switch (type) {
      case TickMarkType.Year:
        return fmt.year.format(date);
      case TickMarkType.Month:
        return fmt.month.format(date);
      case TickMarkType.DayOfMonth:
        return fmt.day.format(date);
      case TickMarkType.Time:
        return fmt.time.format(date);
      case TickMarkType.TimeWithSeconds:
        return fmt.seconds.format(date);
    }
  },
};
