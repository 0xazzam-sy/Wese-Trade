import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render as rtlRender, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { forwardTestApi } from '@/services/api/forwardTest';
import { useAuthStore } from '@/stores/authStore';
import { FORBIDDEN_WORDS } from '@/test/signalFixture';
import type { UserRole } from '@/types/auth';
import type {
  ForwardRun,
  ForwardSignalRow,
  ForwardStats,
  ForwardStatus,
  ForwardStatusCard,
} from '@/types/forwardTest';

import { ForwardTestCard } from './ForwardTestCard';
import { ForwardTestView } from './ForwardTestView';

const STATS: ForwardStats = {
  entered: 4,
  wins: 2,
  losses: 2,
  ambiguous: 0,
  win_rate: 0.5,
  avg_r: 0.25,
  median_r: 0.1,
  expectancy: 0.25,
  profit_factor: 1.5,
  max_drawdown_r: 1.2,
  total_r: 1,
  gross_expectancy: 0.31,
  gross_profit_factor: 1.7,
  avg_hold_bars: 12,
  avg_hold_hours: 3.5,
};

function card(status: ForwardStatus = 'forward_testing'): ForwardStatusCard {
  return {
    name: 'Wese Trade Forward 4.2',
    version: 'wese-trade-forward-4.2-a03e20f1d4',
    fingerprint: '4.2-a03e20f',
    disclaimer_ar: 'الإشارات قيد الاختبار وليست توصيات مضمونة.',
    health: 'running',
    run: {
      id: 1,
      status,
      status_ar: {
        forward_testing: 'اختبار مباشر',
        paused: 'متوقف',
        stopped: 'متوقف',
        passed_forward_test: 'اجتاز الاختبار المباشر',
        failed_forward_test: 'فشل الاختبار المباشر',
      }[status],
      started_at: '2026-10-05T06:00:00+00:00',
      strategy_version: 'wese-trade-forward-4.2-a03e20f1d4',
      fingerprint: '4.2-a03e20f',
    },
    confirmed_signals: 6,
    closed_trades: 4,
    net_expectancy_r: 0.25,
    minimum_required_trades: 150,
  };
}

function run(status: ForwardStatus = 'forward_testing'): ForwardRun {
  return {
    id: 1,
    strategy_version: 'wese-trade-forward-4.2-a03e20f1d4',
    fingerprint: '4.2-a03e20f',
    research_version: 'wese-trade-research-4.1-c590e82e3a',
    started_at: '2026-10-05T06:00:00+00:00',
    stopped_at:
      status === 'forward_testing' || status === 'paused' ? null : '2026-11-10T00:00:00+00:00',
    status,
    status_ar: '',
    symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
    timeframes: ['15m', '30m', '1h'],
    cost_model: { name: 'base', fee_rate: 0.0005, maker_fee_rate: 0.0002, slippage_rate: 0.0002 },
    minimum_required_trades: 150,
    minimum_days: 30,
    notes: '',
    status_history: [],
    config_matches_code: true,
    disclaimer_ar: 'الإشارات قيد الاختبار وليست توصيات مضمونة.',
    health: {
      state: status === 'paused' ? 'paused' : 'running',
      problem: null,
      last_candle_close: 1_791_100_800,
      last_evaluation_at: 1_791_100_805,
      last_persist_ok_at: 1_791_100_806,
      persist_errors: 0,
      unavailable_symbols: [],
      evaluations: 40,
    },
    metrics: {
      counts: {
        confirmed: 6,
        active: 1,
        closed_trades: 4,
        wins: 2,
        losses: 2,
        ambiguous: 0,
        expired_unfilled: 1,
        invalidated: 0,
        ended_by_run_stop: 0,
      },
      all: STATS,
      recent: STATS,
      by_timeframe: { '15m': STATS },
      by_symbol: { BTCUSDT: STATS },
      by_regime: { trend: STATS },
      by_side: { long: STATS },
      by_score_bucket: { '75-79': STATS },
      assessment: { verdict: 'INSUFFICIENT_SAMPLE', reasons: ['closed trades 4 < 150'] },
      elapsed_days: 1.2,
      criteria: { min_closed_trades: 150, min_days: 30 },
    },
  };
}

const ROW: ForwardSignalRow = {
  signal_id: 'BTCUSDT-15m-1',
  strategy_version: 'wese-trade-forward-4.2-a03e20f1d4',
  symbol: 'BTCUSDT',
  timeframe: '15m',
  side: 'long',
  score: 81.4,
  regime: 'trend',
  confirmed_at: '2026-10-05T07:00:00+00:00',
  entry: 100,
  stop: 98,
  tp1: 102,
  tp2: 104,
  tp3: 106,
  state: 'stopped',
  net_r: -1.05,
  gross_r: -1,
};

function login(role: UserRole) {
  useAuthStore.setState({
    status: 'authenticated',
    user: { id: 1, username: 'u', role, is_active: true, created_at: '', last_login_at: null },
  });
}

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function mockApi(status: ForwardStatus = 'forward_testing', rows: ForwardSignalRow[] = [ROW]) {
  vi.spyOn(forwardTestApi, 'status').mockResolvedValue(card(status));
  vi.spyOn(forwardTestApi, 'run').mockResolvedValue(run(status));
  return vi.spyOn(forwardTestApi, 'signals').mockResolvedValue({ items: rows });
}

afterEach(() => {
  vi.restoreAllMocks();
  useAuthStore.setState({ status: 'anonymous', user: null });
});

describe('ForwardTestCard', () => {
  it('shows strategy status, version, closed count and net expectancy', async () => {
    mockApi();
    render(<ForwardTestCard />);
    const section = await screen.findByLabelText('استراتيجية الإشارات');
    await waitFor(() => {
      expect(within(section).getByTestId('forward-status')).toHaveTextContent('اختبار مباشر');
    });
    expect(within(section).getByTestId('forward-fingerprint')).toHaveTextContent('4.2-a03e20f');
    expect(section).toHaveTextContent('4 / 150');
    expect(section).toHaveTextContent('+0.250R');
    expect(section).toHaveTextContent('الإشارات قيد الاختبار وليست توصيات مضمونة.');
  });

  it.each([
    ['paused', 'متوقف'],
    ['failed_forward_test', 'فشل الاختبار المباشر'],
    ['passed_forward_test', 'اجتاز الاختبار المباشر'],
  ] as const)('renders the %s state', async (status, label) => {
    mockApi(status);
    render(<ForwardTestCard />);
    expect(await screen.findByTestId('forward-status')).toHaveTextContent(label);
  });
});

describe('ForwardTestView', () => {
  it('renders the run header, stats, breakdowns and disclaimer', async () => {
    login('analyst');
    mockApi();
    render(<ForwardTestView />);
    const stats = await screen.findByTestId('stats');
    expect(screen.getByText('Wese Trade Forward 4.2')).toBeInTheDocument();
    expect(screen.getByTestId('fingerprint')).toHaveTextContent('4.2-a03e20f');
    expect(screen.getByTestId('run-status')).toHaveTextContent('اختبار مباشر');
    expect(screen.getByTestId('started-utc')).toHaveTextContent('2026-10-05 06:00:00 UTC');
    expect(screen.getByTestId('forward-disclaimer')).toHaveTextContent(
      'الإشارات قيد الاختبار وليست توصيات مضمونة.',
    );
    expect(stats).toHaveTextContent('4 / 150');
    expect(stats).toHaveTextContent('+0.250R');
    expect(stats).toHaveTextContent('1.50');
    expect(screen.getByTestId('assessment')).toHaveTextContent('عينة غير كافية بعد');
    expect(screen.getByTestId('assessment')).toHaveTextContent('غير معايرة');
    for (const title of ['حسب الفريم', 'حسب الرمز', 'حسب حالة السوق', 'حسب قوة الإشارة']) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    const text = screen.getByTestId('forward-test-view').textContent;
    for (const word of FORBIDDEN_WORDS) expect(text).not.toContain(word);
  });

  it('lists signal history and filters by symbol / timeframe / side / state', async () => {
    login('analyst');
    const signals = mockApi();
    render(<ForwardTestView />);
    const table = await screen.findByTestId('history-table');
    const row = within(table).getAllByRole('row')[1];
    expect(row).toHaveTextContent('BTCUSDT');
    expect(row).toHaveTextContent('15m');
    expect(row).toHaveTextContent('شراء');
    expect(row).toHaveTextContent('81/100');
    expect(row).toHaveTextContent('ضُرب وقف الخسارة');
    expect(row).toHaveTextContent('-1.05R');
    expect(row).toHaveTextContent('a03e20f1d4');
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText('الرمز'), 'BTCUSDT');
    await user.selectOptions(screen.getByLabelText('الفريم'), '15m');
    await user.selectOptions(screen.getByLabelText('الاتجاه'), 'short');
    await user.selectOptions(screen.getByLabelText('الحالة'), 'stopped');
    await waitFor(() => {
      expect(signals).toHaveBeenLastCalledWith(
        1,
        { symbol: 'BTCUSDT', timeframe: '15m', side: 'short', state: 'stopped' },
        expect.anything(),
      );
    });
  });

  it('shows the empty history state', async () => {
    login('analyst');
    mockApi('forward_testing', []);
    render(<ForwardTestView />);
    expect(await screen.findByTestId('history-empty')).toBeInTheDocument();
  });

  it('has no tuning controls; analysts see no admin controls', async () => {
    login('analyst');
    mockApi();
    render(<ForwardTestView />);
    await screen.findByTestId('stats');
    expect(screen.queryByTestId('forward-controls')).toBeNull();
    expect(screen.queryByRole('spinbutton')).toBeNull();
    expect(screen.queryByRole('slider')).toBeNull();
    for (const word of ['العتبة', 'الأوزان', 'threshold', 'weight']) {
      expect(screen.getByTestId('forward-test-view').textContent).not.toContain(word);
    }
  });

  it('lets an admin pause a running test (and only pause/resume/stop)', async () => {
    login('admin');
    mockApi();
    const control = vi.spyOn(forwardTestApi, 'control').mockResolvedValue({});
    render(<ForwardTestView />);
    const controls = await screen.findByTestId('forward-controls');
    const buttons = within(controls)
      .getAllByRole('button')
      .map((b) => b.textContent);
    expect(buttons).toEqual(['إيقاف مؤقت', 'إنهاء الاختبار']);
    await userEvent.setup().click(within(controls).getByRole('button', { name: 'إيقاف مؤقت' }));
    expect(control).toHaveBeenCalledWith(1, 'pause', '');
  });

  it('offers resume for a paused run and no controls for a concluded one', async () => {
    login('admin');
    mockApi('paused');
    const { unmount } = render(<ForwardTestView />);
    const controls = await screen.findByTestId('forward-controls');
    expect(within(controls).getByRole('button', { name: 'استئناف' })).toBeInTheDocument();
    expect(screen.getByTestId('run-status')).toHaveTextContent('متوقف');
    unmount();
    vi.restoreAllMocks();
    mockApi('failed_forward_test');
    render(<ForwardTestView />);
    await screen.findByTestId('stats');
    expect(screen.getByTestId('run-status')).toHaveTextContent('فشل الاختبار المباشر');
    expect(screen.queryByTestId('forward-controls')).toBeNull();
  });

  it('offers CSV and JSON export links', async () => {
    login('analyst');
    mockApi();
    render(<ForwardTestView />);
    await screen.findByTestId('stats');
    expect(screen.getByRole('link', { name: /CSV/ })).toHaveAttribute(
      'href',
      expect.stringContaining('/forward-test/runs/1/export?format=csv'),
    );
    expect(screen.getByRole('link', { name: /JSON/ })).toHaveAttribute(
      'href',
      expect.stringContaining('format=json'),
    );
  });
});
