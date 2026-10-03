import { useQuery } from '@tanstack/react-query';
import { Newspaper } from 'lucide-react';

import { EmptyState } from '@/components/ui/EmptyState';
import { Panel } from '@/components/ui/Panel';
import { Spinner } from '@/components/ui/Spinner';
import { newsApi } from '@/services/api/news';

import { NewsCard } from './NewsCard';

export function NewsPanel() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['news', 'latest'],
    queryFn: ({ signal }) => newsApi.latest(signal),
    staleTime: 5 * 60_000,
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
          <EmptyState title="تعذر تحميل الأخبار" description="يرجى المحاولة لاحقاً." />
        ) : data.items.length === 0 ? (
          <EmptyState
            className="flex-1"
            icon={<Newspaper className="size-5" />}
            title={data.available ? 'لا توجد أخبار حالياً' : 'خدمة الأخبار غير مفعّلة بعد'}
            description="ستظهر هنا آخر أخبار العملات الرقمية باللغة العربية مع المصدر والوقت."
          />
        ) : (
          data.items.map((item) => <NewsCard key={item.id} item={item} />)
        )}
      </div>
      <p className="border-line text-fg-subtle text-2xs border-t px-3 py-2 leading-5">
        الأخبار للاطلاع فقط ولا تؤثر إطلاقاً على الإشارات.
      </p>
    </Panel>
  );
}
