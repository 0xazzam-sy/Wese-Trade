import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export type ChartLayout = 'stacked' | 'side-by-side';
export type ChartId = 'primary' | 'secondary';

interface LayoutState {
  chartLayout: ChartLayout;
  /** Not persisted: maximizing is a transient view state. */
  maximizedChart: ChartId | null;
  setChartLayout: (layout: ChartLayout) => void;
  toggleMaximized: (chart: ChartId) => void;
  restore: () => void;
}

export const useLayoutStore = create<LayoutState>()(
  persist(
    (set) => ({
      chartLayout: 'stacked',
      maximizedChart: null,
      setChartLayout: (chartLayout) => {
        set({ chartLayout });
      },
      toggleMaximized: (chart) => {
        set((s) => ({ maximizedChart: s.maximizedChart === chart ? null : chart }));
      },
      restore: () => {
        set({ maximizedChart: null });
      },
    }),
    {
      name: 'neuralshot.layout',
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ chartLayout: s.chartLayout }),
      version: 1,
    },
  ),
);
