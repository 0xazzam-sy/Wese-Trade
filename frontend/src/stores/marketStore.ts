import { create } from 'zustand';

import type { MarketFeedState } from '@/types/market';

/** Low-frequency market state only (feed status). Never per-tick data. */
interface MarketStoreState {
  feed: MarketFeedState | null;
  setFeed: (feed: MarketFeedState | null) => void;
}

export const useMarketStore = create<MarketStoreState>()((set) => ({
  feed: null,
  setFeed: (feed) => {
    set({ feed });
  },
}));
