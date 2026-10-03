import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  className?: string;
  compact?: boolean;
}

/** Explicit placeholder: used wherever real data is not available yet. */
export function EmptyState({ icon, title, description, className, compact }: EmptyStateProps) {
  return (
    <div
      role="status"
      className={cn(
        'flex flex-col items-center justify-center gap-2 text-center',
        compact ? 'px-3 py-4' : 'px-6 py-8',
        className,
      )}
    >
      {icon && (
        <div className="border-line bg-sunken text-fg-subtle mb-1 flex size-10 items-center justify-center rounded-full border">
          {icon}
        </div>
      )}
      <p className="text-fg-muted text-sm font-medium">{title}</p>
      {description && <p className="text-fg-subtle max-w-72 text-xs leading-5">{description}</p>}
    </div>
  );
}
