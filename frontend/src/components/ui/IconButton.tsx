import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/cn';

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible label (also used as tooltip). */
  label: string;
  icon: ReactNode;
  active?: boolean;
  size?: 'sm' | 'md';
}

export function IconButton({
  label,
  icon,
  active = false,
  size = 'md',
  className,
  type = 'button',
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-md transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-40',
        size === 'sm' ? 'size-7' : 'size-8',
        active
          ? 'bg-accent-soft text-accent'
          : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
        className,
      )}
      {...rest}
    >
      {icon}
    </button>
  );
}
