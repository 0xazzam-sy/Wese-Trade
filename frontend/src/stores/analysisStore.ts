import { create } from 'zustand';

import type { ChartId } from '@/stores/layoutStore';
import type { AnalysisSnapshot } from '@/types/analysis';
import type { ExecutionState } from '@/types/execution';
import type { SignalView } from '@/types/signal';

interface AnalysisState {
  /** Latest backend analysis per chart (null while loading / after a switch). */
  byChart: Record<ChartId, AnalysisSnapshot | null>;
  /** Latest signal view per chart (null while loading / after a switch). */
  signals: Record<ChartId, SignalView | null>;
  /** Latest execution timing per chart (1m / 5m / 10m only). */
  executions: Record<ChartId, ExecutionState | null>;
  /** Which chart the analysis panel describes. Not persisted. */
  focused: ChartId;
  /** Chart candles are (re)loading after a symbol/timeframe change (UI feedback only). */
  loading: Record<ChartId, boolean>;
  setLoading: (chart: ChartId, loading: boolean) => void;
  setAnalysis: (chart: ChartId, snapshot: AnalysisSnapshot | null) => void;
  setSignal: (chart: ChartId, view: SignalView | null) => void;
  setExecution: (chart: ChartId, state: ExecutionState | null) => void;
  setFocused: (chart: ChartId) => void;
}

export const useAnalysisStore = create<AnalysisState>()((set) => ({
  byChart: { primary: null, secondary: null },
  signals: { primary: null, secondary: null },
  executions: { primary: null, secondary: null },
  focused: 'primary',
  loading: { primary: false, secondary: false },
  setLoading: (chart, loading) => {
    set((s) =>
      s.loading[chart] === loading ? s : { loading: { ...s.loading, [chart]: loading } },
    );
  },
  setSignal: (chart, view) => {
    set((s) => ({ signals: { ...s.signals, [chart]: view } }));
  },
  setExecution: (chart, state) => {
    set((s) => ({ executions: { ...s.executions, [chart]: state } }));
  },
  setAnalysis: (chart, snapshot) => {
    set((s) => ({ byChart: { ...s.byChart, [chart]: snapshot } }));
  },
  setFocused: (focused) => {
    set({ focused });
  },
}));
