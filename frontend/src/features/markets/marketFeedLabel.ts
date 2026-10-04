import type { StatusTone } from '@/components/ui/StatusDot';
import type { MarketFeedState } from '@/types/market';
import type { ConnectionState } from '@/types/realtime';

/** "بيانات BingX" status, distinct from the app-backend connection. */
export function marketFeedLabel(
  app: ConnectionState,
  feed: MarketFeedState | null,
): { text: string; tone: StatusTone } {
  if (app !== 'connected' || feed === null) return { text: 'غير معروفة', tone: 'idle' };
  switch (feed) {
    case 'connected':
      return { text: 'متصلة', tone: 'ok' };
    case 'degraded':
      return { text: 'متأخرة جزئياً', tone: 'warning' };
    case 'connecting':
    case 'reconnecting':
      return { text: 'جاري إعادة الاتصال', tone: 'pending' };
    case 'disconnected':
      return { text: 'غير متصلة', tone: 'error' };
  }
}
