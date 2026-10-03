import { cn } from '@/lib/cn';

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span
      role="status"
      aria-label={label ?? 'جاري التحميل'}
      className={cn(
        'border-line-strong border-t-accent inline-block size-4 animate-spin rounded-full border-2',
        className,
      )}
    />
  );
}
