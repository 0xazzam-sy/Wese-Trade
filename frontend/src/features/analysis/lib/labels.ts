/** Arabic display labels for backend analysis values. Display only — no logic. */
import type {
  Direction3,
  DirectionalRegime,
  MarketRegime,
  MtfAlignment,
  PremiumDiscount,
  VolatilityRegime,
} from '@/types/analysis';

export const DIRECTION_AR: Record<Direction3, string> = {
  bullish: 'صاعد',
  bearish: 'هابط',
  neutral: 'محايد',
};

export const DIRECTIONAL_REGIME_AR: Record<DirectionalRegime, string> = {
  strong_uptrend: 'اتجاه صاعد قوي',
  uptrend: 'اتجاه صاعد',
  range: 'نطاق عرضي',
  downtrend: 'اتجاه هابط',
  strong_downtrend: 'اتجاه هابط قوي',
  transitional: 'مرحلة انتقالية',
};

export const MARKET_REGIME_AR: Record<MarketRegime, string> = {
  strong_uptrend: 'اتجاه صاعد قوي',
  uptrend: 'اتجاه صاعد',
  ranging: 'نطاق عرضي',
  downtrend: 'اتجاه هابط',
  strong_downtrend: 'اتجاه هابط قوي',
  high_volatility: 'تذبذب مرتفع',
  low_volatility: 'تذبذب منخفض',
  transitional: 'مرحلة انتقالية',
};

export const VOLATILITY_AR: Record<VolatilityRegime, string> = {
  low: 'منخفض',
  normal: 'طبيعي',
  high: 'مرتفع',
  extreme: 'مفرط',
};

export const ALIGNMENT_AR: Record<MtfAlignment, string> = {
  strong_bullish: 'توافق صاعد قوي',
  bullish: 'توافق صاعد',
  strong_bearish: 'توافق هابط قوي',
  bearish: 'توافق هابط',
  countertrend: 'عكس الإطار الأكبر',
  mixed: 'متباين',
  neutral: 'محايد',
  unavailable: 'غير متاح',
};

export const ZONE_AR: Record<PremiumDiscount['zone'], string> = {
  premium: 'منطقة علاوة',
  discount: 'منطقة خصم',
  equilibrium: 'منطقة التوازن',
  above_range: 'فوق النطاق',
  below_range: 'تحت النطاق',
};

export const TIMEFRAME_AR: Record<string, string> = {
  '1m': '1د',
  '5m': '5د',
  '10m': '10د',
  '15m': '15د',
  '30m': '30د',
  '1h': '1س',
};

export const NOT_READY_AR: Record<string, string> = {
  loading_history: 'جاري تحميل التحليل...',
  insufficient_history: 'بيانات غير كافية للتحليل',
  indicators_warming_up: 'جاري تهيئة المؤشرات...',
  history_unavailable: 'تعذر تحميل بيانات التحليل',
};
