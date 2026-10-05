import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

import type { WeatherPlace } from '@/types/weather';

interface WeatherState {
  /** The city the user picked in settings (no device location is ever requested). */
  place: WeatherPlace | null;
  setPlace: (place: WeatherPlace | null) => void;
}

export const useWeatherStore = create<WeatherState>()(
  persist(
    (set) => ({
      place: null,
      setPlace: (place) => {
        set({ place });
      },
    }),
    { name: 'wesetrade.weather', storage: createJSONStorage(() => localStorage) },
  ),
);
