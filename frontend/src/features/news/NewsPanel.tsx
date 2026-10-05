import { useQuery } from '@tanstack/react-query';
import { Newspaper } from 'lucide-react';

import { EmptyState } from '@/components/ui/EmptyState';
import { Panel } from '@/components/ui/Panel';
import { Spinner } from '@/components/ui/Spinner';
import { newsApi } from '@/services/api/news';

import { NewsCard } from './NewsCard';

function emptyTitle(message: string | null): string {
  if (message === 'news_disabled') return 'الأخبار غير مفعّلة';
  if (message === 'news_sources_unreachable') return 'مصادر الأخبار غير متاحة حالياً';
  if (message === 'news_loading') return 'جاري جلب الأخبار';
  return 'لا توجد أخبار حالياً';
}

function emptyDescription(message: string | null): string {
  if (message === 'news_sources_unreachable')
    return 'تحقق من الاتصال بالإنترنت؛ سيعاد المحاولة تلقائياً.';
  if (message === 'news_loading') return 'تُجلب العناوين العربية من مصادرها مع الوقت والمصدر.';
  return 'ستظهر هنا آخر أخبار العملات الرقمية باللغة العربية مع المصدر والوقت.';
}

export function NewsPanel() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['news', 'latest'],
    queryFn: ({ signal }) => newsApi.latest(signal),
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });

  return (
    <Panel
      title="آخر أخبار الكريبتو"
      icon={<Newspaper className="size-4" />}
      className="min-h-0 flex-1"
      bodyClassName="flex flex-col overflow-y-auto"
    >
      <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
        {isPending ? (
          <div className="flex flex-1 items-center justify-center">
            <Spinner />
          </div>
        ) : isError ? (
          <EmptyState
            title="تعذر تحميل الأخبار"
            description="الخادم المحلي غير متاح؛ سيعاد المحاولة تلقائياً."
          />
        ) : data.items.length === 0 ? (
          <EmptyState
            className="flex-1"
            icon={<Newspaper className="size-5" />}
            title={emptyTitle(data.message)}
            description={emptyDescription(data.message)}
          />
        ) : (
          <>
            {data.stale && (
              <p
                role="status"
                className="bg-warning/10 text-warning text-2xs rounded-md px-2 py-1.5"
              >
                مصادر الأخبار غير متاحة حالياً — تُعرض آخر الأخبار المحفوظة.
              </p>
            )}
            {data.items.map((item) => (
              <NewsCard key={item.id} item={item} />
            ))}
          </>
        )}
      </div>
      <p className="border-line text-fg-subtle text-2xs border-t px-3 py-2 leading-5">
        الأخبار للاطلاع فقط ولا تؤثر إطلاقاً على الإشارات.
      </p>
    </Panel>
  );
}
