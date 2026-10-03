/**
 * Locale formatting. Arabic UI text with Latin digits (financial readability).
 * No timezone is hardcoded: Intl uses the browser/user timezone.
 */
export const UI_LOCALE = 'ar-u-nu-latn';

const dateFormatter = new Intl.DateTimeFormat(UI_LOCALE, {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  year: 'numeric',
});

const timeFormatter = new Intl.DateTimeFormat(UI_LOCALE, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

const shortDateTimeFormatter = new Intl.DateTimeFormat(UI_LOCALE, {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

export function formatLongDate(date: Date): string {
  return dateFormatter.format(date);
}

export function formatClockTime(date: Date): string {
  return timeFormatter.format(date);
}

export function formatShortDateTime(date: Date): string {
  return shortDateTimeFormatter.format(date);
}

export function timeZoneLabel(date: Date): string {
  const part = new Intl.DateTimeFormat('en-US', { timeZoneName: 'short' })
    .formatToParts(date)
    .find((p) => p.type === 'timeZoneName');
  return part?.value ?? '';
}
