import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

import type { ChartId } from '@/stores/layoutStore';
import type { SymbolCode, Timeframe } from '@/types/market';

export interface ChartSelection {
  symbol: SymbolCode;
  timeframe: Timeframe;
}

interface ChartState {
  charts: Record<ChartId, ChartSelection>;
  setSymbol: (chart: ChartId, symbol: SymbolCode) => void;
  setTimeframe: (chart: ChartId, timeframe: Timeframe) => void;
}

/** User-selected defaults only; no market data lives in this store. */
export const DEFAULT_CHARTS: Record<ChartId, ChartSelection> = {
  primary: { symbol: 'BTCUSDT', timeframe: '15m' },
  secondary: { symbol: 'ETHUSDT', timeframe: '5m' },
};

export const useChartStore = create<ChartState>()(
  persist(
    (set) => ({
      charts: DEFAULT_CHARTS,
      setSymbol: (chart, symbol) => {
        set((s) => ({ charts: { ...s.charts, [chart]: { ...s.charts[chart], symbol } } }));
      },
      setTimeframe: (chart, timeframe) => {
        set((s) => ({ charts: { ...s.charts, [chart]: { ...s.charts[chart], timeframe } } }));
      },
    }),
    {
      name: 'neuralshot.charts',
      storage: createJSONStorage(() => localStorage),
      version: 1,
    },
  ),
);
