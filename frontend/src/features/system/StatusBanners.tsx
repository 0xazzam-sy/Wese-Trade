import { useQuery } from '@tanstack/react-query';
import { ServerOff, WifiOff } from 'lucide-react';

import { ApiError } from '@/lib/http';
import { systemApi } from '@/services/api/system';
import { useConnectionStore } from '@/stores/connectionStore';
import { useMarketStore } from '@/stores/marketStore';

/**
 * Global, explicit outage notices. The rest of the UI keeps showing the last real data
 * (charts, history, forward test, settings); nothing crashes and nothing is faked.
 */
export function StatusBanners() {
  const health = useQuery({
    queryKey: ['system', 'health'],
    queryFn: ({ signal }) => systemApi.health(signal),
    refetchInterval: 15_000,
    retry: false,
  });
  const realtime = useConnectionStore((s) => s.state);
  const feed = useMarketStore((s) => s.feed);

  const backendDown = health.error instanceof ApiError && health.error.isNetworkError;
  const dbDown = health.data?.database.status === 'unavailable';
  const marketDown =
    !backendDown &&
    realtime === 'connected' &&
    (feed === 'disconnected' || feed === 'reconnecting');

  if (!backendDown && !dbDown && !marketDown) return null;
  return (
    <div className="flex flex-col" data-testid="status-banners">
      {backendDown && (
        <p
          role="alert"
          className="bg-bear-soft text-bear flex items-center gap-2 px-4 py-1.5 text-xs"
        >
          <ServerOff className="size-3.5" />
          الخادم المحلي غير متاح — يعاد الاتصال تلقائياً.
        </p>
      )}
      {dbDown && (
        <p
          role="alert"
          className="bg-bear-soft text-bear flex items-center gap-2 px-4 py-1.5 text-xs"
        >
          <ServerOff className="size-3.5" />
          قاعدة البيانات غير متاحة — لا تُحفظ البيانات الجديدة حالياً.
        </p>
      )}
      {marketDown && (
        <p
          role="status"
          className="bg-warning/10 text-warning flex items-center gap-2 px-4 py-1.5 text-xs"
        >
          <WifiOff className="size-3.5" />
          بيانات السوق غير متصلة — تُعرض آخر البيانات المتاحة ويعاد الاتصال تلقائياً.
        </p>
      )}
    </div>
  );
}
