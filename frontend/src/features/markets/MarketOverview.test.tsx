import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { marketsApi } from '@/services/api/markets';
import { renderApp } from '@/test/render';
import type { MarketSymbol } from '@/types/market';

import { MarketOverview } from './MarketOverview';

const BTC: MarketSymbol = {
  symbol: 'BTCUSDT',
  base_asset: 'BTC',
  quote_asset: 'USDT',
  display_name: 'BTC/USDT',
  contract_type: 'perpetual',
  status: 'active',
  price_precision: 1,
  quantity_precision: 2,
  tick_size: '0.1',
  step_size: '0.01',
  min_quantity: null,
  min_notional: null,
  max_leverage: null,
  trading_enabled: true,
  contract_value: '0.01',
} as MarketSymbol;

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MarketOverview', () => {
  it('shows only real OKX columns (no placeholder signal/confidence columns)', async () => {
    vi.spyOn(marketsApi, 'symbols').mockResolvedValue({
      items: [BTC],
      total: 1,
      default_symbol: 'BTCUSDT',
    } as Awaited<ReturnType<typeof marketsApi.symbols>>);
    vi.spyOn(marketsApi, 'tickers').mockResolvedValue({
      items: [
        {
          symbol: 'BTCUSDT',
          last_price: '62000.5',
          price_change: '620',
          price_change_percent: '1.01',
          open_price: null,
          high_24h: '63000',
          low_24h: '61000',
          volume_24h: '125432.5',
          quote_volume_24h: null,
          bid: null,
          ask: null,
          timestamp: '2026-10-05T09:00:00Z',
        },
      ],
      fetched_at: '2026-10-05T09:00:00Z',
    });
    renderApp(<MarketOverview />);
    expect(await screen.findByText('BTC')).toBeInTheDocument();
    expect(await screen.findByText('125.4K')).toBeInTheDocument(); // real base volume
    const panel = screen.getByLabelText('نظرة على السوق');
    expect(panel.textContent).not.toMatch(/الإشارة|الثقة|بدون إشارات/);
  });
});
