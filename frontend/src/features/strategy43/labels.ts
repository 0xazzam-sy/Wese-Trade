import type { OpportunityDTO, Tier } from '@/types/strategy43';

/** Arabic wording of Strategy 4.3 (one place, so tests and UI never drift). */
export const S43_AR = {
  scannerTitle: 'أفضل الفرص الآن',
  scannerEmpty: 'لا توجد فرص مؤكدة مفتوحة حالياً في السوق — المحرك يفحص الشموع المغلقة باستمرار.',
  scannerStarting: 'محرك الإشارات قيد التشغيل — يجري تحميل بيانات السوق…',
  scannerError: 'تعذر جلب الفرص الآن.',
  engine: 'محرك الإشارات',
  lastMarket: 'آخر تحديث للسوق',
  lastCandle: 'آخر شمعة تم تحليلها',
  lastScan: 'آخر فحص للفرص',
  lastSignal: 'آخر إشارة',
  openCount: 'عدد الفرص المفتوحة',
  todayCount: 'عدد الإشارات اليوم',
  telegram: 'Telegram',
  quality: 'جودة الفرصة',
  strength: 'قوة الإشارة',
  bestOther: 'أفضل فرصة لهذه العملة:',
  noneOther: 'لا توجد فرصة مفتوحة لهذه العملة على 15m / 30m / 1h حالياً.',
  scoreHint: 'قوة الإشارة مقياس لتوافق أدلة السوق من 100 — وليست احتمال ربح.',
} as const;

export const TELEGRAM_STATE_AR: Record<string, string> = {
  connected: 'متصل',
  not_configured: 'غير مُعدّ',
  disabled: 'معطّل',
  no_recipients: 'لا يوجد مستلمون',
  error: 'خطأ في الاتصال',
};

export const ENGINE_TONE: Record<string, string> = {
  running: 'border-accent/40 bg-accent/10 text-accent',
  starting: 'border-warning/40 bg-warning/10 text-warning',
  degraded: 'border-warning/40 bg-warning/10 text-warning',
  stopped: 'border-bear/40 bg-bear/10 text-bear',
};

export function tierText(tier: Tier, tierAr: string): string {
  return `${tier} — ${tierAr}`;
}

/** «منذ 3 د» style relative time (Arabic, Latin digits). */
export function ago(seconds: number | null | undefined, now: number = Date.now() / 1000): string {
  if (seconds === null || seconds === undefined) return '--';
  const d = Math.max(0, Math.round(now - seconds));
  if (d < 60) return `منذ ${String(d)} ث`;
  if (d < 3600) return `منذ ${String(Math.floor(d / 60))} د`;
  if (d < 86400) return `منذ ${String(Math.floor(d / 3600))} س`;
  return `منذ ${String(Math.floor(d / 86400))} يوم`;
}

export function sideText(o: Pick<OpportunityDTO, 'side'>): string {
  return o.side === 'BUY' ? 'BUY — شراء' : 'SELL — بيع';
}
