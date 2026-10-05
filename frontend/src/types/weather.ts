/** A place chosen by the user in settings (Open-Meteo geocoding, Arabic names). */
export interface WeatherPlace {
  name: string;
  country: string | null;
  latitude: number;
  longitude: number;
  timezone: string | null;
}

/** GET /weather/current: real observations or an error, never invented values. */
export interface WeatherCurrent {
  temperature_c: number;
  weather_code: number;
  condition_ar: string;
  wind_kmh: number | null;
  humidity: number | null;
  observed_at: string | null;
  timezone: string | null;
  source: string;
}
