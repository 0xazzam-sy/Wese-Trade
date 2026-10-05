import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/http';
import { weatherApi } from '@/services/api/weather';
import { useWeatherStore } from '@/stores/weatherStore';
import { renderApp } from '@/test/render';

import { WeatherWidget } from './WeatherWidget';

const RIYADH = {
  name: 'الرياض',
  country: 'السعودية',
  latitude: 24.69,
  longitude: 46.72,
  timezone: null,
};

afterEach(() => {
  vi.restoreAllMocks();
  useWeatherStore.setState({ place: null });
});

describe('WeatherWidget', () => {
  it('asks for a city when none is set (no fake temperature)', () => {
    renderApp(<WeatherWidget />);
    expect(screen.getByTestId('weather')).toHaveTextContent('تحديد مدينة الطقس');
    expect(screen.getByTestId('weather').textContent).not.toMatch(/°/);
  });

  it('shows real values from the backend', async () => {
    useWeatherStore.setState({ place: RIYADH });
    vi.spyOn(weatherApi, 'current').mockResolvedValue({
      temperature_c: 31.4,
      weather_code: 2,
      condition_ar: 'غائم جزئياً',
      wind_kmh: 12,
      humidity: 20,
      observed_at: '2026-10-05T12:00',
      timezone: 'Asia/Riyadh',
      source: 'Open-Meteo',
    });
    renderApp(<WeatherWidget />);
    expect(await screen.findByText('31°C')).toBeInTheDocument();
    expect(screen.getByTestId('weather')).toHaveTextContent('غائم جزئياً');
  });

  it('says unavailable on failure', async () => {
    useWeatherStore.setState({ place: RIYADH });
    vi.spyOn(weatherApi, 'current').mockRejectedValue(new ApiError(503, 'weather_unavailable'));
    renderApp(<WeatherWidget />);
    expect(await screen.findByText('الطقس غير متاح', {}, { timeout: 4000 })).toBeInTheDocument();
  });
});
