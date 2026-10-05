import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { newsApi } from '@/services/api/news';
import { renderApp } from '@/test/render';
import type { NewsFeed } from '@/types/news';

import { NewsPanel } from './NewsPanel';

const ITEM = {
  id: 'a1',
  title_ar: 'البيتكوين يرتفع فوق مستوى مقاومة رئيسية',
  source: 'كوينتلغراف بالعربية',
  published_at: '2026-10-05T08:00:00Z',
  url: 'https://ar.example.com/news/btc-1',
  original_language: 'ar',
};

function feed(overrides: Partial<NewsFeed>): NewsFeed {
  return {
    items: [],
    available: true,
    message: null,
    updated_at: null,
    stale: false,
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('NewsPanel', () => {
  it('shows real Arabic headlines with source, time and link; display only', async () => {
    vi.spyOn(newsApi, 'latest').mockResolvedValue(feed({ items: [ITEM] }));
    renderApp(<NewsPanel />);
    expect(await screen.findByText(ITEM.title_ar)).toBeInTheDocument();
    expect(screen.getByText(ITEM.source)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /المصدر/ })).toHaveAttribute('href', ITEM.url);
    expect(
      screen.getByText('الأخبار للاطلاع فقط ولا تؤثر إطلاقاً على الإشارات.'),
    ).toBeInTheDocument();
  });

  it('keeps the last headlines with a notice when sources are unreachable', async () => {
    vi.spyOn(newsApi, 'latest').mockResolvedValue(
      feed({ items: [ITEM], stale: true, message: 'news_sources_unreachable' }),
    );
    renderApp(<NewsPanel />);
    expect(await screen.findByText(/مصادر الأخبار غير متاحة حالياً/)).toBeInTheDocument();
    expect(screen.getByText(ITEM.title_ar)).toBeInTheDocument();
  });

  it.each([
    ['news_sources_unreachable', 'مصادر الأخبار غير متاحة حالياً'],
    ['news_loading', 'جاري جلب الأخبار'],
    ['news_disabled', 'الأخبار غير مفعّلة'],
    [null, 'لا توجد أخبار حالياً'],
  ])('empty state for %s', async (message, title) => {
    vi.spyOn(newsApi, 'latest').mockResolvedValue(feed({ message, available: message === null }));
    renderApp(<NewsPanel />);
    expect(await screen.findByText(title)).toBeInTheDocument();
  });
});
