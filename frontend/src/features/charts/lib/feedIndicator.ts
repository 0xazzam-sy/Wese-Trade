import type { StatusTone } from '@/components/ui/StatusDot';
import type { ChartLoadState } from '@/features/charts/hooks/useMarketChart';
import type { MarketFeedState, StreamState } from '@/types/market';
import type { ConnectionState } from '@/types/realtime';

export interface FeedIndicator {
  tone: StatusTone;
  text: string;
}

/** Truthful per-chart data status, in order of severity. Never claims "live" without proof. */
export function feedIndicator(
  app: ConnectionState,
  feed: MarketFeedState | null,
  stream: StreamState | null,
  load: ChartLoadState,
): FeedIndicator {
  if (app !== 'connected') return { tone: 'error', text: 'غير متصل بالخادم' };
  if (load.status === 'unavailable' || stream === 'unavailable') {
    return { tone: 'idle', text: 'هذا العقد غير متاح حالياً' };
  }
  if (
    feed === 'connecting' ||
    feed === 'reconnecting' ||
    feed === 'disconnected' ||
    stream === 'reconnecting'
  ) {
    return { tone: 'pending', text: 'جاري إعادة الاتصال بمزود البيانات...' };
  }
  if (load.status === 'loading') return { tone: 'pending', text: 'جاري التحميل' };
  if (load.status === 'error') return { tone: 'error', text: 'تعذر تحميل الشموع' };
  if (stream === 'stale') return { tone: 'warning', text: 'البيانات متأخرة' };
  if (stream === 'live') return { tone: 'ok', text: 'مباشر' };
  return { tone: 'pending', text: 'جاري الاشتراك' };
}
