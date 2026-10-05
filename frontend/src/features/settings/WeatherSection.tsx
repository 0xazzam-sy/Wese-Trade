import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useDeferredValue, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { weatherApi } from '@/services/api/weather';
import { useWeatherStore } from '@/stores/weatherStore';

import { Section } from './Section';

/** City picker (Open-Meteo geocoding via the backend). Device location is never requested. */
export function WeatherSection({ enabled }: { enabled: boolean }) {
  const place = useWeatherStore((s) => s.place);
  const setPlace = useWeatherStore((s) => s.setPlace);
  const [query, setQuery] = useState('');
  const deferred = useDeferredValue(query.trim());
  const results = useQuery({
    queryKey: ['weather', 'places', deferred],
    queryFn: ({ signal }) => weatherApi.places(deferred, signal),
    enabled: enabled && deferred.length >= 2,
    retry: false,
  });
  return (
    <Section id="weather" title="الطقس">
      {!enabled ? (
        <p className="text-fg-subtle text-xs">الطقس غير مفعّل في هذا التشغيل.</p>
      ) : (
        <>
          <p className="text-fg-subtle text-2xs mb-2">
            أداة ثانوية للعرض فقط ولا علاقة لها بالإشارات. المصدر: Open-Meteo.
          </p>
          <p className="mb-2 text-sm">
            المدينة الحالية:{' '}
            <span className="font-medium" data-testid="weather-place">
              {place ? `${place.name}${place.country ? `، ${place.country}` : ''}` : 'لم تُحدد'}
            </span>
            {place && (
              <Button
                variant="ghost"
                className="ms-2"
                onClick={() => {
                  setPlace(null);
                }}
              >
                إزالة
              </Button>
            )}
          </p>
          <label className="bg-sunken border-line flex items-center gap-2 rounded-lg border px-2.5">
            <Search className="text-fg-subtle size-3.5" />
            <span className="sr-only">ابحث عن مدينة</span>
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
              }}
              placeholder="ابحث عن مدينة (مثال: الرياض)"
              className="h-9 w-full bg-transparent text-sm outline-none"
            />
          </label>
          {results.isError && (
            <p className="text-warning text-2xs mt-2">خدمة الطقس غير متاحة حالياً.</p>
          )}
          {results.data?.items.length === 0 && (
            <p className="text-fg-subtle text-2xs mt-2">لا توجد نتائج.</p>
          )}
          <ul className="mt-2 space-y-1">
            {(results.data?.items ?? []).map((p) => (
              <li key={`${String(p.latitude)},${String(p.longitude)}`}>
                <button
                  type="button"
                  className="hover:bg-surface-hover w-full rounded-md px-2 py-1.5 text-start text-sm"
                  onClick={() => {
                    setPlace(p);
                    setQuery('');
                  }}
                >
                  {p.name}
                  {p.country ? `، ${p.country}` : ''}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}
