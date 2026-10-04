import { useEffect, useState } from 'react';

import { marketFeed } from '@/services/realtime/marketFeed';

/** UI refresh cap for the price TEXT only. Candle data is never throttled. */
const DISPLAY_INTERVAL_MS = 250;

/** Latest traded price for a symbol from `market.tick`, throttled for display. */
export function useLivePrice(symbol: string): string | null {
  // State is tagged with its symbol so a switch never shows the previous symbol's price.
  const [state, setState] = useState<{ symbol: string; price: string } | null>(null);

  useEffect(() => {
    let pending: string | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      timer = null;
      if (pending !== null) setState({ symbol, price: pending });
    };
    const off = marketFeed.onTick(symbol, (value) => {
      pending = value;
      timer ??= setTimeout(flush, DISPLAY_INTERVAL_MS);
    });
    return () => {
      off();
      if (timer !== null) clearTimeout(timer);
    };
  }, [symbol]);

  return state?.symbol === symbol ? state.price : null;
}
