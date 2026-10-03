import { CloudOff, CloudSun, MapPinOff } from 'lucide-react';
import type { ReactNode } from 'react';

import { Spinner } from '@/components/ui/Spinner';

import { useWeather } from './useWeather';

function Shell({ children, title }: { children: ReactNode; title: string }) {
  return (
    <div
      title={title}
      className="bg-sunken border-line text-fg-muted flex h-8 items-center gap-2 rounded-full border px-3 text-xs"
    >
      {children}
    </div>
  );
}

export function WeatherWidget() {
  const { state, enable } = useWeather();

  switch (state.status) {
    case 'unavailable':
      return (
        <Shell title="لم يتم إعداد مزود الطقس بعد">
          <CloudOff className="text-fg-subtle size-3.5" />
          <span>الطقس غير متاح</span>
        </Shell>
      );
    case 'idle':
      return (
        <button
          type="button"
          onClick={enable}
          className="bg-sunken border-line text-fg-muted hover:text-fg flex h-8 items-center gap-2 rounded-full border px-3 text-xs"
        >
          <CloudSun className="size-3.5" />
          عرض الطقس
        </button>
      );
    case 'locating':
    case 'loading':
      return (
        <Shell title="جاري تحميل الطقس">
          <Spinner className="size-3" />
          <span>جاري التحميل</span>
        </Shell>
      );
    case 'denied':
      return (
        <Shell title="لم يتم السماح بالوصول إلى الموقع">
          <MapPinOff className="text-fg-subtle size-3.5" />
          <span>الموقع غير مسموح</span>
        </Shell>
      );
    case 'error':
      return (
        <Shell title="مزود الطقس غير متاح حالياً">
          <CloudOff className="text-fg-subtle size-3.5" />
          <span>تعذر جلب الطقس</span>
        </Shell>
      );
    case 'ready':
      return (
        <Shell title={state.snapshot.locationName ?? 'الطقس'}>
          <CloudSun className="text-accent size-3.5" />
          <span className="ns-num">{Math.round(state.snapshot.temperatureC)}°C</span>
          <span>{state.snapshot.condition}</span>
        </Shell>
      );
  }
}
