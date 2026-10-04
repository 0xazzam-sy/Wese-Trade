import { cn } from '@/lib/cn';

export type StatusTone = 'ok' | 'pending' | 'warning' | 'error' | 'idle';

const tones: Record<StatusTone, string> = {
  ok: 'bg-bull shadow-[0_0_8px_var(--ns-bull)]',
  pending: 'bg-warning animate-pulse',
  warning: 'bg-warning',
  error: 'bg-bear',
  idle: 'bg-neutral',
};

export function StatusDot({ tone, className }: { tone: StatusTone; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('inline-block size-2 shrink-0 rounded-full', tones[tone], className)}
    />
  );
}
