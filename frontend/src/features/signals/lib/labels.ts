import type { SetupFamily, SignalClass, SignalLifecycleState } from '@/types/signal';

export const SIGNAL_CLASS_AR: Record<SignalClass, string> = {
  STRONG_BUY: 'شراء قوي',
  BUY: 'شراء',
  NEUTRAL: 'محايد',
  SELL: 'بيع',
  STRONG_SELL: 'بيع قوي',
};

/** Tailwind classes from design tokens (no raw colors in components). */
export const SIGNAL_CLASS_STYLE: Record<SignalClass, string> = {
  STRONG_BUY: 'bg-sig-strong-buy/15 text-sig-strong-buy border-sig-strong-buy/40',
  BUY: 'bg-sig-buy/12 text-sig-buy border-sig-buy/30',
  NEUTRAL: 'bg-sig-neutral/10 text-sig-neutral border-sig-neutral/25',
  SELL: 'bg-sig-sell/12 text-sig-sell border-sig-sell/30',
  STRONG_SELL: 'bg-sig-strong-sell/15 text-sig-strong-sell border-sig-strong-sell/40',
};

export const FAMILY_AR: Record<SetupFamily, string> = {
  TREND_CONTINUATION: 'استمرار الاتجاه',
  PULLBACK_CONTINUATION: 'استمرار بعد تصحيح',
  BREAKOUT_CONTINUATION: 'استمرار بعد اختراق',
  LIQUIDITY_REVERSAL: 'انعكاس بعد سحب سيولة',
};

export const STATE_AR: Record<SignalLifecycleState, string> = {
  developing: 'قيد التشكّل',
  confirmed: 'مؤكدة — بانتظار الدخول',
  active: 'نشطة',
  tp1_hit: 'تحقق الهدف الأول',
  tp2_hit: 'تحقق الهدف الثاني',
  tp3_hit: 'تحقق الهدف الثالث',
  stopped: 'ضُرب وقف الخسارة',
  invalidated: 'أُلغيت قبل الدخول',
  expired: 'انتهت دون دخول',
  closed: 'مغلقة',
};

export const COMPONENT_AR: Record<string, string> = {
  htf: 'سياق الإطار الأعلى',
  structure: 'الهيكل',
  liquidity: 'السيولة',
  location: 'الموقع والمناطق',
  trend: 'الاتجاه',
  displacement: 'الاندفاع',
  volume: 'الحجم',
  candle: 'الشمعة',
  momentum: 'الزخم',
};

/** "87/100": a confluence score. Never a percentage or a probability. */
export function formatScore(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return '--';
  return `${Math.round(score).toString()}/100`;
}

export const RISK_NOTE = 'الإشارات تحليلية وليست ضماناً للربح.';
