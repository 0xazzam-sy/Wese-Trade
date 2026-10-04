import { describe, expect, it } from 'vitest';

import { feedIndicator } from './feedIndicator';

const ready = { status: 'ready', empty: false } as const;

describe('feedIndicator', () => {
  it('reports app disconnection first', () => {
    expect(feedIndicator('disconnected', 'connected', 'live', ready).text).toBe('غير متصل بالخادم');
  });
  it('reports market-data provider reconnecting', () => {
    expect(feedIndicator('connected', 'reconnecting', 'live', ready).text).toBe(
      'جاري إعادة الاتصال بمزود البيانات...',
    );
  });
  it('reports stale data and never claims live', () => {
    const result = feedIndicator('connected', 'degraded', 'stale', ready);
    expect(result.text).toBe('البيانات متأخرة');
    expect(result.tone).toBe('warning');
  });
  it('reports unavailable contracts', () => {
    expect(feedIndicator('connected', 'connected', null, { status: 'unavailable' }).text).toBe(
      'هذا العقد غير متاح حالياً',
    );
  });
  it('reports live only with a live stream', () => {
    expect(feedIndicator('connected', 'connected', 'live', ready)).toEqual({
      tone: 'ok',
      text: 'مباشر',
    });
    expect(feedIndicator('connected', 'connected', null, ready).tone).toBe('pending');
  });
});
