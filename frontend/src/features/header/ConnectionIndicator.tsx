import { StatusDot, type StatusTone } from '@/components/ui/StatusDot';
import { useConnectionStore } from '@/stores/connectionStore';
import type { ConnectionState } from '@/types/realtime';

const LABELS: Record<ConnectionState, { text: string; tone: StatusTone }> = {
  connected: { text: 'متصل', tone: 'ok' },
  connecting: { text: 'جاري الاتصال', tone: 'pending' },
  disconnected: { text: 'غير متصل', tone: 'error' },
};

export function ConnectionIndicator() {
  const state = useConnectionStore((s) => s.state);
  const { text, tone } = LABELS[state];

  return (
    <div
      role="status"
      aria-live="polite"
      title="حالة الاتصال اللحظي بالخادم"
      className="bg-sunken border-line flex h-8 items-center gap-2 rounded-full border px-3"
    >
      <StatusDot tone={tone} />
      <span className="text-fg-muted text-xs font-medium">النظام: {text}</span>
    </div>
  );
}
