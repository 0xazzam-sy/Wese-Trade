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
  message: string | null;
}
