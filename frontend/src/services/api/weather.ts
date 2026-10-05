import { apiRequest } from '@/lib/http';
import type { WeatherCurrent, WeatherPlace } from '@/types/weather';

/** Weather goes through the local backend only (the UI never calls third parties). */
export const weatherApi = {
  places(query: string, signal?: AbortSignal): Promise<{ items: WeatherPlace[] }> {
    const q = new URLSearchParams({ q: query });
    return apiRequest(`/weather/places?${q.toString()}`, signal ? { signal } : {});
  },

  current(place: WeatherPlace, signal?: AbortSignal): Promise<WeatherCurrent> {
    const q = new URLSearchParams({ lat: String(place.latitude), lon: String(place.longitude) });
    return apiRequest<WeatherCurrent>(`/weather/current?${q.toString()}`, signal ? { signal } : {});
  },
};
