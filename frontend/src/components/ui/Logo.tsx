import { cn } from '@/lib/cn';

/** Wese Trade mark: three connected nodes forming an upward stroke. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden className={cn('size-8', className)}>
      <rect
        width="32"
        height="32"
        rx="9"
        className="fill-sunken stroke-line-strong"
        strokeWidth="1"
      />
      <g strokeLinecap="round" strokeWidth="1.6">
        <path d="M9 22 L16 10 L23 18" className="stroke-accent" />
        <path d="M9 22 L23 18" className="stroke-violet" opacity="0.5" />
      </g>
      <circle cx="9" cy="22" r="2.3" className="fill-accent" />
      <circle cx="16" cy="10" r="2.3" className="fill-violet" />
      <circle cx="23" cy="18" r="2.3" className="fill-accent" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn('ns-ltr text-fg text-base font-semibold tracking-tight', className)}>
      Wese <span className="text-accent">Trade</span>
    </span>
  );
}
