import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

interface PanelProps {
  title?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  as?: 'section' | 'aside' | 'div';
  'aria-label'?: string;
}

export function Panel({
  title,
  icon,
  actions,
  children,
  className,
  bodyClassName,
  as: Tag = 'section',
  ...rest
}: PanelProps) {
  return (
    <Tag className={cn('ns-panel flex min-h-0 flex-col', className)} {...rest}>
      {(title ?? actions) !== undefined && (
        <header className="border-line flex items-center gap-2 border-b px-3.5 py-2.5">
          {icon && <span className="text-accent shrink-0">{icon}</span>}
          {title && <h2 className="text-fg truncate text-sm font-semibold">{title}</h2>}
          {actions && <div className="ms-auto flex items-center gap-1.5">{actions}</div>}
        </header>
      )}
      <div className={cn('min-h-0 flex-1', bodyClassName)}>{children}</div>
    </Tag>
  );
}
