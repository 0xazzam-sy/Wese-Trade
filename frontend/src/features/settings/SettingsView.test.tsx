import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { forwardTestApi } from '@/services/api/forwardTest';
import { systemApi } from '@/services/api/system';
import { usersApi } from '@/services/api/users';
import { weatherApi } from '@/services/api/weather';
import { useAuthStore } from '@/stores/authStore';
import { useThemeStore } from '@/stores/themeStore';
import { useWeatherStore } from '@/stores/weatherStore';
import { loginAs, renderApp } from '@/test/render';
import type { RuntimeInfo } from '@/types/system';

import { SettingsView } from './SettingsView';

const RUNTIME: RuntimeInfo = {
  app_version: '1.0.0',
  mode: 'development',
  market_provider: 'OKX',
  strategy: {
    name: 'Wese Trade Strategy 4.3',
    version: 'wese-trade-strategy-4.3-6044cea28a',
    fingerprint: '4.3-6044cea',
    status: 'live',
  },
  baseline: {
    name: 'Wese Trade Forward 4.2',
    version: 'wese-trade-forward-4.2-a03e20f1d4',
    fingerprint: '4.2-a03e20f',
    status: 'forward_testing',
  },
  news_enabled: true,
  weather_enabled: true,
};

function mocks() {
  vi.spyOn(systemApi, 'runtime').mockResolvedValue(RUNTIME);
  vi.spyOn(forwardTestApi, 'status').mockResolvedValue({
    name: 'Wese Trade Forward 4.2',
    version: RUNTIME.baseline?.version ?? '',
    fingerprint: '4.2-a03e20f',
    disclaimer_ar: '',
    health: 'running',
    run: {
      id: 1,
      status: 'forward_testing',
      status_ar: 'اختبار مباشر',
      started_at: '2026-10-05T09:13:04+00:00',
      strategy_version: RUNTIME.baseline?.version ?? '',
      fingerprint: '4.2-a03e20f',
    },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  useAuthStore.setState({ status: 'anonymous', user: null });
  useWeatherStore.setState({ place: null });
});

describe('SettingsView', () => {
  it('shows account, strategy fingerprint, provider, version; no tuning controls', async () => {
    loginAs('viewer');
    mocks();
    renderApp(<SettingsView />, '/settings');
    expect(await screen.findByText('4.3-6044cea')).toHaveAttribute(
      'data-testid',
      'settings-fingerprint',
    );
    expect(screen.getByTestId('app-version')).toHaveTextContent('1.0.0');
    expect(screen.getByText('viewer-user')).toBeInTheDocument();
    expect(screen.getByText('مشاهد')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText('استراتيجية الإشارات')).toHaveTextContent(
        '4.2-a03e20f · متابعة مباشرة',
      );
    });
    expect(screen.queryByLabelText('تنبيهات Telegram')).toBeNull(); // admin only
    expect(screen.getByLabelText('مزود بيانات السوق')).toHaveTextContent('OKX');
    expect(screen.getByTestId('settings-view')).toHaveTextContent(
      'الإشارات تحليلية وليست توصيات مضمونة',
    );
    expect(screen.queryByLabelText('المستخدمون')).toBeNull(); // admin only
    expect(screen.queryByTestId('desktop-actions')).toBeNull(); // browser: no desktop buttons
    expect(screen.queryByRole('spinbutton')).toBeNull();
    expect(screen.getByTestId('settings-view').textContent).not.toMatch(/العتبة|الأوزان/);
  });

  it('switches the theme', async () => {
    loginAs('viewer');
    mocks();
    renderApp(<SettingsView />, '/settings');
    await userEvent.setup().click(await screen.findByRole('radio', { name: 'فاتح' }));
    expect(useThemeStore.getState().theme).toBe('light');
  });

  it('lets an administrator add a user and change a role', async () => {
    loginAs('admin');
    mocks();
    const admin = {
      id: 1,
      username: 'admin-user',
      role: 'admin' as const,
      is_active: true,
      created_at: '',
      last_login_at: null,
    };
    vi.spyOn(usersApi, 'list').mockResolvedValue({ items: [admin] });
    const create = vi
      .spyOn(usersApi, 'create')
      .mockResolvedValue({ ...admin, id: 2, username: 'ana', role: 'analyst' });
    const update = vi.spyOn(usersApi, 'update').mockResolvedValue(admin);
    renderApp(<SettingsView />, '/settings');
    const section = await screen.findByLabelText('المستخدمون');
    const user = userEvent.setup();
    await user.type(within(section).getByLabelText('اسم المستخدم الجديد'), 'ana');
    await user.type(
      within(section).getByLabelText('كلمة مرور المستخدم الجديد'),
      'Analyst-Strong-1',
    );
    await user.selectOptions(within(section).getByLabelText('دور المستخدم الجديد'), 'analyst');
    await user.click(within(section).getByRole('button', { name: 'إضافة مستخدم' }));
    expect(create).toHaveBeenCalledWith({
      username: 'ana',
      password: 'Analyst-Strong-1',
      role: 'analyst',
    });
    await user.selectOptions(await within(section).findByLabelText('دور admin-user'), 'viewer');
    await waitFor(() => {
      expect(update).toHaveBeenCalledWith(1, { role: 'viewer' });
    });
  });

  it('picks a weather city through the backend (never device location)', async () => {
    loginAs('viewer');
    mocks();
    const geo = vi.fn();
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition: geo, watchPosition: geo },
    });
    vi.spyOn(weatherApi, 'places').mockResolvedValue({
      items: [
        {
          name: 'الرياض',
          country: 'السعودية',
          latitude: 24.69,
          longitude: 46.72,
          timezone: 'Asia/Riyadh',
        },
      ],
    });
    renderApp(<SettingsView />, '/settings');
    const user = userEvent.setup();
    await user.type(await screen.findByPlaceholderText('ابحث عن مدينة (مثال: الرياض)'), 'الرياض');
    await user.click(await screen.findByRole('button', { name: 'الرياض، السعودية' }));
    expect(useWeatherStore.getState().place?.name).toBe('الرياض');
    expect(screen.getByTestId('weather-place')).toHaveTextContent('الرياض');
    expect(geo).not.toHaveBeenCalled();
  });
});
