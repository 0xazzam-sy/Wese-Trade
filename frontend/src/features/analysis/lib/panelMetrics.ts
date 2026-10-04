import type { AnalysisSnapshot, Direction3, StructureState } from '@/types/analysis';

import { DIRECTION_AR, MARKET_REGIME_AR, TIMEFRAME_AR, VOLATILITY_AR, ZONE_AR } from './labels';

export type Tone = 'bull' | 'bear' | 'neutral' | 'warning' | 'muted';

export interface PanelMetric {
  key: string;
  label: string;
  value: string;
  detail?: string;
  tone: Tone;
}

export const METRIC_LABELS: { key: string; label: string }[] = [
  { key: 'trend', label: 'الاتجاه' },
  { key: 'regime', label: 'حالة السوق' },
  { key: 'swing', label: 'الهيكل الرئيسي' },
  { key: 'internal', label: 'الهيكل الداخلي' },
  { key: 'liquidity', label: 'السيولة' },
  { key: 'volatility', label: 'التذبذب' },
  { key: 'momentum', label: 'الزخم' },
  { key: 'volume', label: 'الحجم' },
  { key: 'zone', label: 'المنطقة الحالية' },
];

const EMPTY = '--';
const RECENT_SWEEP_CANDLES = 10;
const TF_SECONDS: Record<string, number> = {
  '1m': 60,
  '5m': 300,
  '10m': 600,
  '15m': 900,
  '30m': 1800,
  '1h': 3600,
};

export function directionTone(direction: Direction3 | null | undefined): Tone {
  if (direction === 'bullish') return 'bull';
  if (direction === 'bearish') return 'bear';
  return 'neutral';
}

function structureValue(
  state: StructureState | null | undefined,
): Pick<PanelMetric, 'value' | 'detail' | 'tone'> {
  if (!state) return { value: EMPTY, tone: 'muted' };
  const event = state.last_event;
  const tag = event ? (event.type === 'CHOCH' ? 'CHoCH' : 'BOS') : null;
  return {
    value: tag ? `${DIRECTION_AR[state.direction]} · ${tag}` : DIRECTION_AR[state.direction],
    tone: directionTone(state.direction),
    ...(event ? { detail: `آخر حدث ${DIRECTION_AR[event.direction]}` } : {}),
  };
}

/** Builds the nine analysis cells. Pure: every value comes from the backend snapshot. */
export function panelMetrics(snapshot: AnalysisSnapshot | null): PanelMetric[] {
  if (!snapshot?.analysis_ready) {
    return METRIC_LABELS.map((m) => ({ ...m, value: EMPTY, tone: 'muted' as const }));
  }
  const s = snapshot;
  const values: Record<string, Pick<PanelMetric, 'value' | 'detail' | 'tone'>> = {};

  values.trend = s.trend
    ? {
        value: DIRECTION_AR[s.trend.direction],
        detail: `EMA ${s.trend.stack === 'mixed' ? 'متداخلة' : DIRECTION_AR[s.trend.stack]}`,
        tone: directionTone(s.trend.direction),
      }
    : { value: EMPTY, tone: 'muted' };

  values.regime = s.regime
    ? {
        value: MARKET_REGIME_AR[s.regime.primary],
        tone:
          s.regime.primary === 'high_volatility'
            ? 'warning'
            : directionTone(
                s.regime.directional.includes('up')
                  ? 'bullish'
                  : s.regime.directional.includes('down')
                    ? 'bearish'
                    : 'neutral',
              ),
      }
    : { value: EMPTY, tone: 'muted' };

  values.swing = structureValue(s.swing_structure);
  values.internal = structureValue(s.internal_structure);

  const liq = s.liquidity;
  if (liq) {
    const step = TF_SECONDS[s.timeframe] ?? 60;
    const recent = [...liq.sweeps]
      .reverse()
      .find(
        (sw) => s.candle_time !== null && s.candle_time - sw.time <= RECENT_SWEEP_CANDLES * step,
      );
    const developing = s.developing?.sweeps[0];
    if (developing) {
      values.liquidity = {
        value:
          developing.side === 'buy_side'
            ? 'سحب سيولة علوية (قيد التكوّن)'
            : 'سحب سيولة سفلية (قيد التكوّن)',
        tone: 'warning',
      };
    } else if (recent) {
      values.liquidity = {
        value: recent.side === 'buy_side' ? 'سُحبت سيولة علوية' : 'سُحبت سيولة سفلية',
        detail: `جودة ${Math.round(recent.quality)}`,
        tone: 'warning',
      };
    } else {
      values.liquidity = {
        value: `علوية ${String(liq.active_buy_side)} · سفلية ${String(liq.active_sell_side)}`,
        tone: 'neutral',
      };
    }
  } else values.liquidity = { value: EMPTY, tone: 'muted' };

  values.volatility = s.volatility
    ? {
        value: VOLATILITY_AR[s.volatility.regime],
        detail: `ATR ${s.volatility.atr_pct.toFixed(2)}%`,
        tone:
          s.volatility.regime === 'high' || s.volatility.regime === 'extreme'
            ? 'warning'
            : 'neutral',
      }
    : { value: EMPTY, tone: 'muted' };

  const rsi = s.momentum?.rsi;
  values.momentum =
    rsi !== null && rsi !== undefined
      ? {
          value: `RSI ${rsi.toFixed(0)}`,
          detail:
            (s.momentum?.rsi_slope ?? 0) > 0
              ? 'زخم متصاعد'
              : (s.momentum?.rsi_slope ?? 0) < 0
                ? 'زخم متراجع'
                : 'زخم مستقر',
          tone: rsi >= 50 ? 'bull' : 'bear',
        }
      : { value: EMPTY, tone: 'muted' };

  const rel = s.volume?.relative;
  values.volume =
    rel !== null && rel !== undefined
      ? {
          value: `×${rel.toFixed(2)}`,
          detail: s.volume?.spike ? 'ارتفاع حاد' : s.volume?.contraction ? 'انكماش' : 'ضمن المعدل',
          tone: s.volume?.spike ? 'warning' : 'neutral',
        }
      : { value: EMPTY, tone: 'muted' };

  const pd = s.premium_discount;
  values.zone = pd
    ? {
        value: ZONE_AR[pd.zone],
        detail: `${pd.position.toFixed(0)}% من النطاق${s.ote?.price_in_zone ? ' · ضمن OTE' : ''}`,
        tone: 'neutral', // context only: never colored as a direction
      }
    : { value: EMPTY, tone: 'muted' };

  return METRIC_LABELS.map((m) => ({
    ...m,
    ...(values[m.key] ?? { value: EMPTY, tone: 'muted' }),
  }));
}

export function timeframeLabel(tf: string): string {
  return TIMEFRAME_AR[tf] ?? tf;
}
