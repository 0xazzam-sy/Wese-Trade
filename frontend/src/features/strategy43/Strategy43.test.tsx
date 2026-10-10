import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { applySignalEvent } from '@/features/signals/lib/reduce';
import { TelegramSection } from '@/features/settings/TelegramSection';
import { strategy43Api } from '@/services/api/strategy43';
import { telegramApi } from '@/services/api/telegram';
import { useAnalysisStore } from '@/stores/analysisStore';
import { DEFAULT_CHARTS, useChartStore } from '@/stores/chartStore';
import { loginAs, renderApp } from '@/test/render';
import type { EngineHealth, OpportunityDTO } from '@/types/strategy43';
import type { TelegramSettings } from '@/types/telegram';

import { EngineStatusCard } from './EngineStatusCard';
import { OpportunityScanner } from './OpportunityScanner';

afterEach(() => {
  vi.restoreAllMocks();
  useChartStore.setState({ charts: DEFAULT_CHARTS });
  useAnalysisStore.setState({ focused: 'primary' });
});

function opp(o: Partial<OpportunityDTO>): OpportunityDTO {
  return {
    id: 'x', symbol: 'BTCUSDT', timeframe: '30m', side: 'BUY', tier: 'A', tier_ar: 'قوية',
    score: 84, family: 'TREND_CONTINUATION', family_ar: 'استمرار الاتجاه', state: 'confirmed',
    state_ar: 'بانتظار الدخول', entry: 100, stop: 99, targets: [101, 102, 103], rr: [1, 2, 3],
    confirmed_time: 1, valid_until: 2, regime: 'UPTREND', regime_ar: 'اتجاه صاعد', ...o,
  }; // prettier-ignore
}

describe('OpportunityScanner («أفضل الفرص الآن»)', () => {
  it('lists ranked opportunities and opens one on the focused chart', async () => {
    vi.spyOn(strategy43Api, 'opportunities').mockResolvedValue({
      items: [
        opp({ id: 'a', symbol: 'BTCUSDT', timeframe: '30m', tier: 'A', score: 84 }),
        opp({ id: 'b', symbol: 'SOLUSDT', timeframe: '15m', side: 'SELL', tier: 'B', score: 77 }),
        opp({ id: 'c', symbol: 'DOGEUSDT', timeframe: '1h', tier: 'C', score: 66 }),
      ],
      universe_size: 30,
      markets_scanned: 30,
      symbols_with_opportunity: 3,
      last_scan_at: Date.now() / 1000 - 30,
      state: 'running',
    });
    renderApp(<OpportunityScanner />);
    const rows = await screen.findAllByTestId('scanner-row');
    expect(rows.map((r) => r.textContent)).toEqual([
      '1BTCUSDTBUY30mA84',
      '2SOLUSDTSELL15mB77',
      '3DOGEUSDTBUY1hC66',
    ]);
    expect(screen.getByTestId('scanner-coverage')).toHaveTextContent('3 / 30');
    const [, second] = rows;
    if (!second) throw new Error('missing row');
    await userEvent.click(second);
    expect(useChartStore.getState().charts.primary).toEqual({
      symbol: 'SOLUSDT',
      timeframe: '15m',
    });
  });

  it('says honestly when there are no open opportunities', async () => {
    vi.spyOn(strategy43Api, 'opportunities').mockResolvedValue({
      items: [], universe_size: 30, markets_scanned: 30, symbols_with_opportunity: 0,
      last_scan_at: null, state: 'running',
    }); // prettier-ignore
    renderApp(<OpportunityScanner />);
    expect(await screen.findByTestId('scanner-empty')).toBeInTheDocument();
  });
});

describe('EngineStatusCard («محرك الإشارات»)', () => {
  const health = (o: Partial<EngineHealth>): EngineHealth =>
    ({
      state: 'running', state_ar: 'نشط', problems: [], name: 'Wese Trade Strategy 4.3',
      version: 'wese-trade-strategy-4.3-6044cea28a', fingerprint: '4.3-6044cea', started_at: 1,
      universe: [], universe_size: 30, streams: 90, subscribed: 90, markets_scanned: 30,
      timeframes: ['15m', '30m', '1h'], open_opportunities: 4,
      open_by_tier: { 'A+': 0, A: 1, B: 1, C: 2 }, symbols_with_opportunity: 3,
      market_status: 'connected', evaluations: 10, confirmed: 2,
      last_candle_close: Date.now() / 1000 - 60, last_market_update: Date.now() / 1000 - 5,
      last_scan_at: Date.now() / 1000 - 5, last_signal_at: null,
      signals: { today: { total: 7, by_tier: {} } },
      telegram: null, ...o,
    }); // prettier-ignore

  it('shows the live engine fields', async () => {
    vi.spyOn(strategy43Api, 'health').mockResolvedValue(health({}));
    renderApp(<EngineStatusCard />);
    expect(await screen.findByTestId('engine-state')).toHaveTextContent('نشط');
    const card = screen.getByTestId('engine-status');
    for (const label of [
      'آخر تحديث للسوق',
      'آخر شمعة تم تحليلها',
      'آخر فحص للفرص',
      'آخر إشارة',
      'عدد الفرص المفتوحة',
      'عدد الإشارات اليوم',
      'Telegram',
    ])
      // prettier-ignore
      expect(card).toHaveTextContent(label);
    expect(card).toHaveTextContent('Strategy 4.3-6044cea');
  });

  it('shows the real technical problem instead of a generic "inactive" message', async () => {
    vi.spyOn(strategy43Api, 'health').mockResolvedValue(
      health({
        state: 'degraded',
        state_ar: 'يعمل مع مشكلة',
        problems: ['الاتصال ببيانات السوق (OKX) مقطوع — لا يمكن تحليل شموع جديدة'],
      }),
    );
    renderApp(<EngineStatusCard />);
    expect(await screen.findByRole('alert')).toHaveTextContent('OKX');
    expect(screen.getByTestId('engine-status')).not.toHaveTextContent('غير نشطة');
  });
});

describe('signal reducer', () => {
  it('keeps the best opportunity of the symbol from 4.3 events', () => {
    const best = opp({ timeframe: '1h' });
    const v = applySignalEvent(
      null,
      'signal.updated',
      { symbol: 'BTCUSDT', timeframe: '15m', best },
      { symbol: 'BTCUSDT', timeframe: '15m' },
    );
    expect(v?.best).toEqual(best);
    const cleared = applySignalEvent(
      v,
      'signal.updated',
      { symbol: 'BTCUSDT', timeframe: '15m', best: null },
      { symbol: 'BTCUSDT', timeframe: '15m' },
    );
    expect(cleared?.best).toBeNull();
  });
});

const RECIPIENT = {
  id: 1, name: 'Ali', chat_id: '42', enabled: true, buy: true, sell: true,
  timeframes: [], symbols: [], lifecycle: true,
}; // prettier-ignore

describe('TelegramSection', () => {
  const settings: TelegramSettings = {
    configured: true, token_hint: '••••AbCd', bot_username: 'wese_bot', enabled: true,
    events: { NEW: true, TP1: true, TP2: true, TP3: true, STOPPED: true, EXPIRED: false },
    status: 'connected', status_detail: '', checked_at: null,
    recipients: [RECIPIENT],
  }; // prettier-ignore

  it('never shows the token, only a masked hint; manages recipients and tests', async () => {
    loginAs('admin');
    vi.spyOn(telegramApi, 'settings').mockResolvedValue(settings);
    vi.spyOn(telegramApi, 'deliveries').mockResolvedValue([]);
    const add = vi
      .spyOn(telegramApi, 'addRecipient')
      .mockResolvedValue({ ...RECIPIENT, id: 2, name: 'Sara', chat_id: '43' });
    const fixture = vi.spyOn(telegramApi, 'sendTestSignal').mockResolvedValue({ deliveries: [7] });
    renderApp(<TelegramSection />);
    expect(await screen.findByTestId('telegram-status')).toHaveTextContent('متصل');
    expect(screen.getByTestId('telegram-section')).toHaveTextContent('••••AbCd');
    expect(screen.getByLabelText('رمز البوت (Bot Token)')).toHaveValue('');
    expect(screen.getByRole('checkbox', { name: 'انتهاء الصلاحية' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'إشارة جديدة BUY / SELL' })).toBeChecked();
    await userEvent.type(screen.getByLabelText('اسم المستلم'), 'Sara');
    await userEvent.type(screen.getByLabelText('Chat ID'), '43');
    await userEvent.click(screen.getByRole('button', { name: 'إضافة' }));
    await waitFor(() => {
      expect(add).toHaveBeenCalledWith({ name: 'Sara', chat_id: '43' });
    });
    await userEvent.click(screen.getByRole('button', { name: 'إشارة TEST — BUY' }));
    await waitFor(() => {
      expect(fixture).toHaveBeenCalledWith('BUY');
    });
    act(() => undefined);
  });
});
