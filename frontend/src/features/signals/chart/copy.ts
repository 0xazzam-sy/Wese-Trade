/** Arabic wording of the chart signal UX (one place, so tests and UI never drift). */
export const CHART_SIGNAL_AR = {
  question: 'موقف النظام الآن',
  neutral: 'محايد',
  neutralDetail: 'لا توجد فرصة مناسبة حالياً',
  buy: 'BUY — شراء',
  sell: 'SELL — بيع',
  enabled: 'Strategy 4.3',
  researchOnly: 'توقيت الدخول',
  researchOnlyDetail: 'قرار التوقيت لهذا الفريم في لوحة التنفيذ',
  paused: 'محرك الإشارات قيد التشغيل — يجري تحليل الشموع المغلقة',
  forward: 'Strategy 4.3',
  unproven: 'تحليلية',
  disclaimer: 'الإشارة تحليلية وليست توصية مضمونة.',
  uncalibrated: 'غير معايرة',
  strategyName: 'Strategy 4.3',
  bestOther: 'أفضل فرصة لهذه العملة:',
  legendButton: 'شرح الشارت',
  legendAuthority:
    'هذه العلامات تشرح تحليل السوق فقط. قرار BUY أو SELL يصدر حصراً من محرك إشارات Wese Trade.',
} as const;

/** The chart legend: structure terms explained in Arabic (abbreviations stay on the chart). */
export const LEGEND_TERMS: readonly { term: string; ar: string }[] = [
  { term: 'HH', ar: 'قمة أعلى' },
  { term: 'HL', ar: 'قاع أعلى' },
  { term: 'LH', ar: 'قمة أدنى' },
  { term: 'LL', ar: 'قاع أدنى' },
  { term: 'BOS', ar: 'كسر في بنية السوق' },
  { term: 'iBOS', ar: 'كسر داخلي في البنية' },
  { term: 'CHoCH', ar: 'تغير في سلوك/بنية السوق' },
  { term: 'iCHoCH', ar: 'تغير داخلي في البنية' },
  { term: 'Sweep', ar: 'سحب سيولة' },
  { term: 'EQH', ar: 'قمم متساوية تقريباً' },
  { term: 'EQL', ar: 'قيعان متساوية تقريباً' },
  { term: 'OB', ar: 'Order Block / منطقة أوامر' },
  { term: 'FVG', ar: 'فجوة قيمة عادلة' },
  { term: 'OTE', ar: 'منطقة دخول مثالية وفق التحليل' },
  { term: 'Premium', ar: 'منطقة سعر مرتفعة نسبياً ضمن النطاق' },
  { term: 'Discount', ar: 'منطقة سعر منخفضة نسبياً ضمن النطاق' },
];

/** Local time of a signal, Latin digits: 2026-09-18 08:00. */
export function formatSignalTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

/** "wese-trade-strategy-4.3-6044cea28a" → "4.3-6044cea" (also 4.2 forward versions). */
export function fingerprintOf(version: string): string {
  const m = /-(\d+\.\d+)-([0-9a-f]{7})[0-9a-f]*$/.exec(version);
  return m ? `${m[1] ?? ''}-${m[2] ?? ''}` : version;
}
