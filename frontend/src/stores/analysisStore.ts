import { create } from 'zustand';

import type { ChartId } from '@/stores/layoutStore';
import type { AnalysisSnapshot } from '@/types/analysis';

interface AnalysisState {
  /** Latest backend analysis per chart (null while loading / after a switch). */
  byChart: Record<ChartId, AnalysisSnapshot | null>;
  /** Which chart the analysis panel describes. Not persisted. */
  focused: ChartId;
  setAnalysis: (chart: ChartId, snapshot: AnalysisSnapshot | null) => void;
  setFocused: (chart: ChartId) => void;
}

export const useAnalysisStore = create<AnalysisState>()((set) => ({
  byChart: { primary: null, secondary: null },
  focused: 'primary',
  setAnalysis: (chart, snapshot) => {
    set((s) => ({ byChart: { ...s.byChart, [chart]: snapshot } }));
  },
  setFocused: (focused) => {
    set({ focused });
  },
}));
