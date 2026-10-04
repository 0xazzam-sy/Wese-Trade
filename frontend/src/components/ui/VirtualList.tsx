import { type ReactNode, type UIEvent, useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/cn';

interface VirtualListProps<T> {
  items: readonly T[];
  rowHeight: number;
  /** Visible height in px; the list scrolls inside it. */
  height: number;
  overscan?: number;
  renderRow: (item: T, index: number) => ReactNode;
  getKey: (item: T) => string;
  /** Index to keep in view (keyboard navigation). */
  activeIndex?: number;
  className?: string;
  role?: string;
  id?: string;
  ariaLabel?: string;
}

/** Fixed-row-height windowing: renders only visible rows (hundreds of symbols stay cheap). */
export function VirtualList<T>({
  items,
  rowHeight,
  height,
  overscan = 6,
  renderRow,
  getKey,
  activeIndex,
  className,
  role,
  id,
  ariaLabel,
}: VirtualListProps<T>) {
  const ref = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el || activeIndex === undefined || activeIndex < 0) return;
    const top = activeIndex * rowHeight;
    if (top < el.scrollTop) el.scrollTop = top;
    else if (top + rowHeight > el.scrollTop + height) el.scrollTop = top + rowHeight - height;
  }, [activeIndex, rowHeight, height]);

  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(items.length, Math.ceil((scrollTop + height) / rowHeight) + overscan);

  return (
    <div
      ref={ref}
      id={id}
      role={role}
      aria-label={ariaLabel}
      onScroll={(e: UIEvent<HTMLDivElement>) => {
        setScrollTop(e.currentTarget.scrollTop);
      }}
      className={cn('relative overflow-y-auto', className)}
      style={{ height }}
    >
      <div style={{ height: items.length * rowHeight, position: 'relative' }}>
        {items.slice(start, end).map((item, offset) => {
          const index = start + offset;
          return (
            <div
              key={getKey(item)}
              style={{
                position: 'absolute',
                top: index * rowHeight,
                height: rowHeight,
                insetInline: 0,
              }}
            >
              {renderRow(item, index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
