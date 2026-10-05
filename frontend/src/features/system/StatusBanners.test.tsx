import { act, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/http';
import { systemApi } from '@/services/api/system';
import { useConnectionStore } from '@/stores/connectionStore';
import { useMarketStore } from '@/stores/marketStore';
import { renderApp } from '@/test/render';

import { StatusBanners } from './StatusBanners';

const OK = {
  status: 'ok' as const,
  service: 'Wese Trade',
  version: '1.0.0',
  api_version: 'v1',
  database: { status: 'ok' as const },
  timestamp: '',
};

afterEach(() => {
  vi.restoreAllMocks();
  act(() => {
    useConnectionStore.setState({ state: 'disconnected' });
    useMarketStore.setState({ feed: null });
  });
});

describe('StatusBanners', () => {
  it('nothing when everything is up', async () => {
    vi.spyOn(systemApi, 'health').mockResolvedValue(OK);
    act(() => {
      useConnectionStore.setState({ state: 'connected' });
      useMarketStore.setState({ feed: 'connected' });
    });
    renderApp(<StatusBanners />);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId('status-banners')).toBeNull();
  });

  it('market data disconnected', async () => {
    vi.spyOn(systemApi, 'health').mockResolvedValue(OK);
    act(() => {
      useConnectionStore.setState({ state: 'connected' });
      useMarketStore.setState({ feed: 'disconnected' });
    });
    renderApp(<StatusBanners />);
    expect(await screen.findByRole('status')).toHaveTextContent('بيانات السوق غير متصلة');
  });

  it('local backend unavailable', async () => {
    vi.spyOn(systemApi, 'health').mockRejectedValue(new ApiError(0, 'network_error'));
    renderApp(<StatusBanners />);
    expect(await screen.findByRole('alert')).toHaveTextContent('الخادم المحلي غير متاح');
  });

  it('database unavailable', async () => {
    vi.spyOn(systemApi, 'health').mockResolvedValue({
      ...OK,
      status: 'degraded',
      database: { status: 'unavailable' },
    });
    renderApp(<StatusBanners />);
    expect(await screen.findByRole('alert')).toHaveTextContent('قاعدة البيانات غير متاحة');
  });
});
