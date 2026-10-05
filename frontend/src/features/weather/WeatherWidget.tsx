import { useQuery } from '@tanstack/react-query';
import { CloudOff, CloudSun, MapPin } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router';

import { Spinner } from '@/components/ui/Spinner';
import { weatherApi } from '@/services/api/weather';
import { useWeatherStore } from '@/stores/weatherStore';

const SHELL =
  'bg-sunken border-line text-fg-muted flex h-8 items-center gap-2 rounded-full border px-3 text-xs';

function Shell({ children, title }: { children: ReactNode; title: string }) {
  return (
    <div title={title} className={SHELL} data-testid="weather">
      {children}
    </div>
  );
}

/** Secondary utility: real Open-Meteo data via the local backend, never coupled to signals. */
export function WeatherWidget() {
  const place = useWeatherStore((s) => s.place);
  const query = useQuery({
    queryKey: ['weather', place?.latitude, place?.longitude],
    queryFn: ({ signal }) =>
      place ? weatherApi.current(place, signal) : Promise.reject(new Error('no_place')),
    enabled: place !== null,
    staleTime: 10 * 60_000,
    refetchInterval: 15 * 60_000,
    retry: 1,
  });

  if (!place) {
    return (
      <Link to="/settings#weather" className={`${SHELL} hover:text-fg`} data-testid="weather">
        <MapPin className="size-3.5" />
        تحديد مدينة الطقس
      </Link>
    );
  }
  if (query.isPending) {
    return (
      <Shell title="جاري تحميل الطقس">
        <Spinner className="size-3" />
        <span>{place.name}</span>
      </Shell>
    );
  }
  if (query.isError) {
    return (
      <Shell title="مزود الطقس غير متاح حالياً">
        <CloudOff className="text-fg-subtle size-3.5" />
        <span>الطقس غير متاح</span>
      </Shell>
    );
  }
  const w = query.data;
  return (
    <Shell title={`${place.name} — ${w.condition_ar} (المصدر: ${w.source})`}>
      <CloudSun className="text-accent size-3.5" />
      <span className="ns-num">{Math.round(w.temperature_c)}°C</span>
      <span>{w.condition_ar}</span>
      <span className="text-fg-subtle">{place.name}</span>
    </Shell>
  );
}
