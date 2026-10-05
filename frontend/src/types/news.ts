export interface NewsItem {
  id: string;
  title_ar: string;
  source: string;
  published_at: string; // UTC ISO-8601
  url: string;
  original_language: string | null;
}

export interface NewsFeed {
  items: NewsItem[];
  available: boolean;
  /** news_loading | news_sources_unreachable | news_disabled */
  message: string | null;
  updated_at: string | null;
  /** Sources unreachable right now: showing the last real headlines. */
  stale: boolean;
}
