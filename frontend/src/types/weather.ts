export interface Coordinates {
  latitude: number;
  longitude: number;
}

export interface WeatherSnapshot {
  temperatureC: number;
  condition: string;
  locationName: string | null;
  observedAt: string;
}
