import { StatusDot } from '@/components/ui/StatusDot';
import { marketFeedLabel } from '@/features/markets/marketFeedLabel';
import { useConnectionStore } from '@/stores/connectionStore';
import { useMarketStore } from '@/stores/marketStore';

export function MarketFeedIndicator() {
  const app = useConnectionStore((s) => s.state);
  const feed = useMarketStore((s) => s.feed);
  const { text, tone } = marketFeedLabel(app, feed);
  return (
    <div
      role="status"
      title="حالة تغذية بيانات BingX"
      className="bg-sunken border-line flex h-8 items-center gap-2 rounded-full border px-3"
    >
      <StatusDot tone={tone} />
      <span className="text-fg-muted text-xs font-medium">بيانات BingX: {text}</span>
    </div>
  );
}
