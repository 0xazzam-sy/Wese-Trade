import { useCallback, useEffect, useRef, useState } from 'react';

import { getWeatherProvider, requestApproximateLocation } from '@/services/weather/weatherService';
import type { WeatherSnapshot } from '@/types/weather';

export type WeatherState =
  | { status: 'unavailable' } // no provider configured
  | { status: 'idle' } // provider ready; waiting for the user to opt in
  | { status: 'locating' }
  | { status: 'loading' }
  | { status: 'denied' } // location permission refused
  | { status: 'error' } // provider failed
  | { status: 'ready'; snapshot: WeatherSnapshot };

/**
 * Optional weather. Location is requested only after an explicit user action and with
 * low accuracy. Failures are contained here and never affect the rest of the app.
 */
export function useWeather(): { state: WeatherState; enable: () => void } {
  const provider = getWeatherProvider();
  const [state, setState] = useState<WeatherState>(() =>
    provider.configured ? { status: 'idle' } : { status: 'unavailable' },
  );
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const enable = useCallback(() => {
    if (!provider.configured) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    void (async () => {
      setState({ status: 'locating' });
      let coords;
      try {
        coords = await requestApproximateLocation();
      } catch (error) {
        const denied = error instanceof Error && error.message === 'permission_denied';
        setState({ status: denied ? 'denied' : 'error' });
        return;
      }
      setState({ status: 'loading' });
      try {
        const snapshot = await provider.getCurrent(coords, controller.signal);
        if (!controller.signal.aborted) setState({ status: 'ready', snapshot });
      } catch {
        if (!controller.signal.aborted) setState({ status: 'error' });
      }
    })();
  }, [provider]);

  return { state, enable };
}
