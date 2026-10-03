import { apiRequest } from '@/lib/http';
import type { NewsFeed } from '@/types/news';

export const newsApi = {
  latest(signal?: AbortSignal): Promise<NewsFeed> {
    return apiRequest<NewsFeed>('/news', signal ? { signal } : {});
  },
};
