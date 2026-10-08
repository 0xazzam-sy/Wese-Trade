import type { OverlayToggles } from '@/stores/overlayStore';
import type { AnalysisSnapshot, Pivot, StructureEvent } from '@/types/analysis';
import type { SignalDTO } from '@/types/signal';

/**
 * Pure translation of a backend snapshot into drawables. No analysis happens here:
 * every coordinate is a backend-computed price/time. `to: null` = extends to the right edge.
 */
export type ZoneKind =
  'fvg-bull' | 'fvg-bear' | 'ob-bull' | 'ob-bear' | 'premium' | 'discount' | 'equilibrium' | 'ote';
export type LineKind =
  | 'liq-buy'
  | 'liq-sell'
  | 'bos-bull'
  | 'bos-bear'
  | 'protected'
  | 'eq-line'
  | 'plan-entry'
  | 'plan-stop'
  | 'plan-target'
  | 'sr-support'
  | 'sr-resistance';
export type Tone = 'bull' | 'bear' | 'neutral' | 'accent' | 'violet' | 'warning';

export interface OverlayZone {
  id: string;
  from: number;
  to: number | null;
  top: number;
  bottom: number;
  kind: ZoneKind;
  faded: boolean;
  label?: string;
}

export interface OverlayLine {
  id: string;
  from: number;
  to: number | null;
  price: number;
  kind: LineKind;
  dashed: boolean;
  faded: boolean;
  label?: string;
}

export interface OverlayLabel {
  id: string;
  time: number;
  price: number;
  text: string;
  tone: Tone;
  position: 'above' | 'below';
  faded: boolean;
}

export interface OverlayModel {
  zones: OverlayZone[];
  lines: OverlayLine[];
  labels: OverlayLabel[];
}

export const EMPTY_MODEL: OverlayModel = { zones: [], lines: [], labels: [] };

const MAX_SWING_PIVOTS = 12;
const MAX_INTERNAL_PIVOTS = 16;
const MAX_SWING_EVENTS = 6;
const MAX_INTERNAL_EVENTS = 3;
const MAX_POOLS = 8;
const MAX_SWEEPS = 6;
const MAX_FVGS = 8;
const MAX_OBS = 6;

function eventTag(e: StructureEvent): string {
  const base = e.type === 'CHOCH' ? 'CHoCH' : 'BOS';
  return e.layer === 'internal' ? `i${base}` : base;
}

function pivotLabel(p: Pivot, internal: boolean): OverlayLabel {
  const high = p.side === 'high';
  return {
    id: `pv:${p.id}`,
    time: p.time,
    price: p.price,
    text: internal ? '·' : p.type === 'HIGH' || p.type === 'LOW' ? (high ? 'H' : 'L') : p.type,
    tone: internal
      ? 'neutral'
      : p.type === 'HH' || p.type === 'HL'
        ? 'bull'
        : p.type === 'LH' || p.type === 'LL'
          ? 'bear'
          : 'neutral',
    position: high ? 'above' : 'below',
    faded: p.status === 'developing',
  };
}

function eventLines(
  events: StructureEvent[],
  max: number,
): { lines: OverlayLine[]; labels: OverlayLabel[] } {
  const recent = events.slice(-max);
  return {
    lines: recent.map((e) => ({
      id: `ev:${e.id}`,
      from: e.level_time,
      to: e.time,
      price: e.level,
      kind: e.direction === 'bullish' ? 'bos-bull' : 'bos-bear',
      dashed: e.layer === 'internal',
      faded: e.layer === 'internal',
    })),
    labels: recent.map((e) => ({
      id: `evl:${e.id}`,
      time: e.time,
      price: e.level,
      text: eventTag(e),
      tone: e.direction === 'bullish' ? 'bull' : 'bear',
      position: e.direction === 'bullish' ? 'above' : 'below',
      faded: e.layer === 'internal',
    })),
  };
}

/** Trade-plan line labels: Arabic first, the industry abbreviation after it. */
export const PLAN_LABELS = {
  entry: 'الدخول ENTRY',
  stop: 'وقف الخسارة SL',
  target: (n: number) => `الهدف ${String(n)} TP${String(n)}`,
} as const;

/**
 * Entry / SL / TP1-3 lines of the OPEN confirmed signal of this chart only. BUY/SELL markers
 * are drawn separately (SignalMarkersOverlay) from confirmed signals; closed signals keep
 * their marker but never their plan lines, and nothing is drawn for developing hypotheses.
 */
export function tradePlanLines(open: SignalDTO | null, toggles: OverlayToggles): OverlayLine[] {
  const lines: OverlayLine[] = [];
  if (!toggles.tradePlan || !open) return lines;
  const from = open.trigger_time;
  const plan = open.plan;
  const zone = plan.entry_model === 'ZONE_ENTRY' && plan.entry_low !== plan.entry_high;
  lines.push({
    id: `plan:${open.id}:entry`,
    from,
    to: null,
    price: open.entry_price ?? plan.preferred_entry,
    kind: 'plan-entry',
    dashed: false,
    faded: false,
    label: PLAN_LABELS.entry,
  });
  if (zone && open.entry_price === null) {
    for (const [edge, price] of [
      ['low', plan.entry_low],
      ['high', plan.entry_high],
    ] as const) {
      lines.push({
        id: `plan:${open.id}:entry-${edge}`,
        from,
        to: null,
        price,
        kind: 'plan-entry',
        dashed: true,
        faded: true,
      });
    }
  }
  lines.push({
    id: `plan:${open.id}:sl`,
    from,
    to: null,
    price: plan.stop,
    kind: 'plan-stop',
    dashed: false,
    faded: false,
    label: PLAN_LABELS.stop,
  });
  plan.targets.forEach((t, i) => {
    lines.push({
      id: `plan:${open.id}:tp${String(i + 1)}`,
      from,
      to: null,
      price: t.price,
      kind: 'plan-target',
      dashed: i < open.targets_hit,
      faded: i < open.targets_hit,
      label: PLAN_LABELS.target(i + 1),
    });
  });
  return lines;
}

export function buildOverlayModel(
  snapshot: AnalysisSnapshot | null,
  toggles: OverlayToggles,
  openSignal: SignalDTO | null = null,
  /** Extra backend-computed lines (execution plan, S/R levels with strength). */
  extraLines: readonly OverlayLine[] = [],
): OverlayModel {
  // The trade plan comes from the signal, not the analysis: drawn even while analysis loads.
  if (!snapshot?.analysis_ready) {
    const plan = [...tradePlanLines(openSignal, toggles), ...extraLines];
    return plan.length ? { zones: [], lines: plan, labels: [] } : EMPTY_MODEL;
  }
  const zones: OverlayZone[] = [];
  const lines: OverlayLine[] = [];
  const labels: OverlayLabel[] = [];
  const dev = snapshot.developing;

  if (toggles.structure) {
    const swing = snapshot.swing_structure;
    const internal = snapshot.internal_structure;
    swing?.pivots.slice(-MAX_SWING_PIVOTS).forEach((p) => labels.push(pivotLabel(p, false)));
    internal?.pivots.slice(-MAX_INTERNAL_PIVOTS).forEach((p) => labels.push(pivotLabel(p, true)));
    for (const [state, max] of [
      [swing, MAX_SWING_EVENTS],
      [internal, MAX_INTERNAL_EVENTS],
    ] as const) {
      if (!state) continue;
      const out = eventLines(state.events, max);
      lines.push(...out.lines);
      labels.push(...out.labels);
    }
    for (const level of [swing?.protected_high, swing?.protected_low]) {
      if (!level?.active) continue;
      lines.push({
        id: `prot:${level.id}`,
        from: level.time,
        to: null,
        price: level.price,
        kind: 'protected',
        dashed: true,
        faded: false,
        label: level.side === 'high' ? 'مقاومة · قمة محمية' : 'دعم · قاع محمي',
      });
    }
    dev?.swing_pivots.forEach((p) => labels.push(pivotLabel(p, false)));
    [...(dev?.swing_breaks ?? []), ...(dev?.internal_breaks ?? [])].forEach((b, i) => {
      const tag = b.type === 'CHOCH' ? 'CHoCH' : 'BOS';
      labels.push({
        id: `devbrk:${String(i)}:${b.layer}`,
        time: snapshot.forming_time ?? snapshot.candle_time ?? 0,
        price: b.level,
        text: `${b.layer === 'internal' ? 'i' : ''}${tag}?`,
        tone: b.direction === 'bullish' ? 'bull' : 'bear',
        position: b.direction === 'bullish' ? 'above' : 'below',
        faded: true,
      });
    });
  }

  if (toggles.liquidity && snapshot.liquidity) {
    const liq = snapshot.liquidity;
    const price = snapshot.price ?? 0;
    const nearest = liq.pools
      .filter((p) => p.status === 'active')
      .sort((a, b) => Math.abs(a.level - price) - Math.abs(b.level - price))
      .slice(0, MAX_POOLS);
    // Only the closest pool on each side gets a text label: meaningful levels, no clutter.
    const named = new Set(
      (['buy_side', 'sell_side'] as const)
        .map((side) => nearest.find((p) => p.side === side)?.id)
        .filter(Boolean),
    );
    nearest.forEach((p) => {
      const equal = p.source === 'equal_highs' || p.source === 'equal_lows';
      const side = p.side === 'buy_side' ? 'سيولة علوية' : 'سيولة سفلية';
      const tag = equal ? (p.source === 'equal_highs' ? 'EQH' : 'EQL') : null;
      const label = named.has(p.id) ? (tag ? `${side} · ${tag}` : side) : tag;
      lines.push({
        id: `pool:${p.id}`,
        from: p.time,
        to: null,
        price: p.level,
        kind: p.side === 'buy_side' ? 'liq-buy' : 'liq-sell',
        dashed: true,
        faded: !equal && !named.has(p.id),
        ...(label ? { label } : {}),
      });
    });
    liq.sweeps.slice(-MAX_SWEEPS).forEach((s) => {
      labels.push({
        id: `sw:${s.id}`,
        time: s.time,
        price: s.extreme,
        text: '✕ Sweep',
        tone: 'warning',
        position: s.side === 'buy_side' ? 'above' : 'below',
        faded: false,
      });
    });
    dev?.sweeps.forEach((s, i) => {
      labels.push({
        id: `devsw:${String(i)}:${s.pool_id}`,
        time: snapshot.forming_time ?? snapshot.candle_time ?? 0,
        price: s.extreme,
        text: '✕?',
        tone: 'warning',
        position: s.side === 'buy_side' ? 'above' : 'below',
        faded: true,
      });
    });
  }

  if (toggles.fvg) {
    const live = (snapshot.fair_value_gaps ?? []).filter(
      (g) => g.status === 'active' || g.status === 'mitigated',
    );
    [...live.slice(-MAX_FVGS), ...(dev?.fair_value_gaps ?? [])].forEach((g) => {
      zones.push({
        id: `fvg:${g.id}`,
        from: g.time,
        to: null,
        top: g.top,
        bottom: g.bottom,
        kind: g.type === 'bullish_fvg' ? 'fvg-bull' : 'fvg-bear',
        faded: g.status === 'mitigated' || g.status_detail === 'developing',
        label: 'FVG',
      });
    });
  }

  if (toggles.orderBlocks) {
    (snapshot.order_blocks ?? [])
      .filter((b) => b.status === 'active' || b.status === 'mitigated')
      .slice(-MAX_OBS)
      .forEach((b) => {
        zones.push({
          id: `ob:${b.id}`,
          from: b.time,
          to: null,
          top: b.top,
          bottom: b.bottom,
          kind: b.type === 'bullish_ob' ? 'ob-bull' : 'ob-bear',
          faded: b.status === 'mitigated',
          label: 'OB',
        });
      });
  }

  const pd = snapshot.premium_discount;
  if (toggles.premiumDiscount && pd) {
    const from = Math.min(pd.high_time, pd.low_time);
    zones.push(
      {
        id: 'pd:premium',
        from,
        to: null,
        top: pd.high,
        bottom: pd.equilibrium_upper,
        kind: 'premium',
        faded: false,
        label: 'Premium',
      },
      {
        id: 'pd:discount',
        from,
        to: null,
        top: pd.equilibrium_lower,
        bottom: pd.low,
        kind: 'discount',
        faded: false,
        label: 'Discount',
      },
    );
    lines.push({
      id: 'pd:eq',
      from,
      to: null,
      price: pd.equilibrium,
      kind: 'eq-line',
      dashed: true,
      faded: false,
      label: 'EQ 50%',
    });
  }

  const ote = snapshot.ote;
  if (toggles.ote && ote?.active) {
    zones.push({
      id: 'ote',
      from: ote.impulse_end_time,
      to: null,
      top: ote.upper,
      bottom: ote.lower,
      kind: 'ote',
      faded: false,
      label: 'OTE',
    });
  }

  lines.push(...tradePlanLines(openSignal, toggles), ...extraLines);

  return { zones, lines, labels };
}
