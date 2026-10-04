import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { searchSymbols } from '@/features/markets/search';
import { marketsApi } from '@/services/api/markets';
import type { MarketSymbol } from '@/types/market';

import { SymbolSelector } from './SymbolSelector';

const sym = (base: string, precision = 2): MarketSymbol => ({
  symbol: `${base}USDT`,
  base_asset: base,
  quote_asset: 'USDT',
  display_name: `${base}/USDT`,
  contract_type: 'perpetual',
  status: 'active',
  price_precision: precision,
  quantity_precision: 2,
  tick_size: '0.01',
  step_size: '0.01',
  min_quantity: null,
  min_notional: null,
  max_leverage: 100,
  trading_enabled: true,
  contract_value: '0.01',
  contract_value_currency: base,
});

const SYMBOLS = [sym('BTC', 1), sym('ETH'), sym('ETHFI'), sym('WBTC'), sym('SOL')];

describe('symbol search', () => {
  it('matches BTC, BTCUSDT and BTC-USDT, exact base first', () => {
    expect(searchSymbols(SYMBOLS, 'btc').map((s) => s.symbol)).toEqual(['BTCUSDT', 'WBTCUSDT']);
    expect(searchSymbols(SYMBOLS, 'BTCUSDT')[0]?.symbol).toBe('BTCUSDT');
    expect(searchSymbols(SYMBOLS, 'btc-usdt')[0]?.symbol).toBe('BTCUSDT');
    expect(searchSymbols(SYMBOLS, 'ETH').map((s) => s.symbol)).toEqual(['ETHUSDT', 'ETHFIUSDT']);
  });
});

describe('SymbolSelector', () => {
  beforeEach(() => {
    vi.spyOn(marketsApi, 'symbols').mockResolvedValue({
      items: SYMBOLS,
      total: SYMBOLS.length,
      default_symbol: 'BTCUSDT',
      refreshed_at: null,
    });
    vi.spyOn(marketsApi, 'tickers').mockResolvedValue({
      items: [
        {
          symbol: 'ETHUSDT',
          last_price: '2500.5',
          price_change: '25',
          price_change_percent: '1.01',
          open_price: '2475.5',
          high_24h: '2510',
          low_24h: '2400',
          volume_24h: '1',
          quote_volume_24h: '1',
          bid: null,
          ask: null,
          timestamp: '2026-10-03T12:00:00Z',
        },
      ],
      fetched_at: '2026-10-03T12:00:00Z',
    });
  });

  it('loads the real list, filters instantly and selects with the keyboard', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SymbolSelector value="BTCUSDT" onChange={onChange} />
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole('button', { name: /اختيار العقد/ }));
    const listbox = await screen.findByRole('listbox');
    expect(within(listbox).getAllByRole('option')).toHaveLength(SYMBOLS.length);

    await user.type(screen.getByRole('combobox'), 'eth');
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(2);
    expect(await screen.findByText('2,500.50')).toBeInTheDocument();
    expect(screen.getByText('+1.01%')).toBeInTheDocument();

    await user.keyboard('{ArrowDown}{Enter}');
    expect(onChange).toHaveBeenCalledWith('ETHFIUSDT');
  });

  it('Enter right after typing selects from the just-typed results', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SymbolSelector value="BTCUSDT" onChange={onChange} />
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole('button', { name: /اختيار العقد/ }));
    await screen.findByRole('listbox');
    await user.type(screen.getByRole('combobox'), 'sol{Enter}');
    expect(onChange).toHaveBeenCalledWith('SOLUSDT');
  });
});
