import { ExternalLink } from 'lucide-react';

import { formatShortDateTime } from '@/lib/format';
import type { NewsItem } from '@/types/news';

/** One Arabic news headline with source, local timestamp and external link. */
export function NewsCard({ item }: { item: NewsItem }) {
  return (
    <article className="border-line hover:bg-surface-hover rounded-lg border p-3 transition-colors">
      <h3 className="text-fg text-sm leading-6 font-medium">{item.title_ar}</h3>
      <div className="text-fg-subtle text-2xs mt-2 flex items-center gap-2">
        <span className="truncate">{item.source}</span>
        <span aria-hidden>•</span>
        <time dateTime={item.published_at}>{formatShortDateTime(new Date(item.published_at))}</time>
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent ms-auto inline-flex items-center gap-1 hover:underline"
        >
          المصدر
          <ExternalLink className="size-3" />
        </a>
      </div>
    </article>
  );
}
