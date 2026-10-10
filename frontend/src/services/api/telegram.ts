import { apiRequest } from '@/lib/http';
import type {
  TelegramChat,
  TelegramDelivery,
  TelegramEvent,
  TelegramRecipient,
  TelegramRecipientInput,
  TelegramSettings,
  TelegramTestResult,
} from '@/types/telegram';

const withSignal = (signal?: AbortSignal) => (signal ? { signal } : {});

/** Administrator-only Telegram configuration. */
export const telegramApi = {
  settings(signal?: AbortSignal): Promise<TelegramSettings> {
    return apiRequest<TelegramSettings>('/telegram', withSignal(signal));
  },
  setToken(token: string): Promise<TelegramSettings> {
    return apiRequest<TelegramSettings>('/telegram/token', { method: 'PUT', body: { token } });
  },
  clearToken(): Promise<TelegramSettings> {
    return apiRequest<TelegramSettings>('/telegram/token', { method: 'DELETE' });
  },
  testConnection(): Promise<TelegramSettings> {
    return apiRequest<TelegramSettings>('/telegram/test-connection', { method: 'POST' });
  },
  setOptions(body: {
    enabled?: boolean;
    events?: Partial<Record<TelegramEvent, boolean>>;
  }): Promise<TelegramSettings> {
    return apiRequest<TelegramSettings>('/telegram/options', { method: 'PATCH', body });
  },
  sendTestMessage(recipientId?: number): Promise<TelegramTestResult[]> {
    const q = recipientId === undefined ? '' : `?recipient_id=${String(recipientId)}`;
    return apiRequest(`/telegram/test-message${q}`, { method: 'POST' });
  },
  sendTestSignal(side: 'BUY' | 'SELL'): Promise<{ deliveries: number[] }> {
    return apiRequest('/telegram/test-signal', { method: 'POST', body: { side } });
  },
  chats(): Promise<TelegramChat[]> {
    return apiRequest('/telegram/chats');
  },
  addRecipient(body: TelegramRecipientInput): Promise<TelegramRecipient> {
    return apiRequest('/telegram/recipients', { method: 'POST', body });
  },
  updateRecipient(id: number, body: TelegramRecipientInput): Promise<TelegramRecipient> {
    return apiRequest(`/telegram/recipients/${String(id)}`, { method: 'PATCH', body });
  },
  deleteRecipient(id: number): Promise<void> {
    return apiRequest<undefined>(`/telegram/recipients/${String(id)}`, { method: 'DELETE' });
  },
  deliveries(limit = 30, signal?: AbortSignal): Promise<TelegramDelivery[]> {
    return apiRequest(`/telegram/deliveries?limit=${String(limit)}`, withSignal(signal));
  },
};
