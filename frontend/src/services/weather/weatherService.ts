import type { Coordinates, WeatherSnapshot } from '@/types/weather';

/**
 * Weather is optional, independent from trading, and must never block the app.
 * Phase 1 ships the contract plus a "not configured" provider only.
 */
export interface WeatherProvider {
  readonly id: string;
  readonly configured: boolean;
  getCurrent(coords: Coordinates, signal?: AbortSignal): Promise<WeatherSnapshot>;
}

export class WeatherUnavailableError extends Error {
  constructor() {
    super('Weather provider is not configured');
    this.name = 'WeatherUnavailableError';
  }
}

export const unconfiguredWeatherProvider: WeatherProvider = {
  id: 'none',
  configured: false,
  getCurrent() {
    return Promise.reject(new WeatherUnavailableError());
  },
};

export function getWeatherProvider(): WeatherProvider {
  return unconfiguredWeatherProvider;
}

/** Coarse, user-initiated location lookup (never called automatically). */
export function requestApproximateLocation(timeoutMs = 10_000): Promise<Coordinates> {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) {
      reject(new Error('geolocation_unsupported'));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        resolve({
          // Round to ~1km: weather does not need precise coordinates.
          latitude: Math.round(position.coords.latitude * 100) / 100,
          longitude: Math.round(position.coords.longitude * 100) / 100,
        });
      },
      (error) => {
        reject(
          new Error(error.code === error.PERMISSION_DENIED ? 'permission_denied' : 'unavailable'),
        );
      },
      { enableHighAccuracy: false, maximumAge: 30 * 60_000, timeout: timeoutMs },
    );
  });
}
