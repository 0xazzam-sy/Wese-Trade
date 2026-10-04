import { StatusDot } from '@/components/ui/StatusDot';
import type { FeedIndicator } from '@/features/charts/lib/feedIndicator';

export function StreamBadge({ indicator }: { indicator: FeedIndicator }) {
  return (
    <span
      role="status"
      className="text-fg-subtle text-2xs flex items-center gap-1.5 px-1.5"
      title={indicator.text}
    >
      <StatusDot tone={indicator.tone} />
      <span className="hidden whitespace-nowrap @2xl:inline">{indicator.text}</span>
    </span>
  );
}
