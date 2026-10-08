/**
 * EMA lines drawn on every chart (20 / 50 / 200). Same recursion as the backend execution
 * analyzer (first value = first close, then value += k * (close - value)); points before
 * the period has elapsed are not drawn, so a line never shows an un-warmed value.
 */
export const EMA_PERIODS = [20, 50, 200] as const;
export type EmaPeriod = (typeof EMA_PERIODS)[number];

export interface EmaPoint {
  time: number;
  value: number;
}

export class EmaTrack {
  private readonly k: number;
  /** EMA after each bar (index-aligned with the chart's bars). */
  private values: number[] = [];

  constructor(readonly period: number) {
    this.k = 2 / (period + 1);
  }

  private next(prev: number | undefined, close: number): number {
    return prev === undefined ? close : prev + this.k * (close - prev);
  }

  /** Full recompute (history load / historical correction). */
  reset(closes: readonly number[]): void {
    const out: number[] = [];
    let prev: number | undefined;
    for (const c of closes) {
      prev = this.next(prev, c);
      out.push(prev);
    }
    this.values = out;
  }

  /** The newest bar appended (`replace` = false) or updated in place (`replace` = true). */
  push(close: number, replace: boolean): number {
    if (replace) this.values.pop();
    const value = this.next(this.values[this.values.length - 1], close);
    this.values.push(value);
    return value;
  }

  visible(index: number): boolean {
    return index >= this.period - 1;
  }

  points(times: readonly number[]): EmaPoint[] {
    const out: EmaPoint[] = [];
    this.values.forEach((value, i) => {
      const time = times[i];
      if (time !== undefined && this.visible(i)) out.push({ time, value });
    });
    return out;
  }

  get length(): number {
    return this.values.length;
  }
}
