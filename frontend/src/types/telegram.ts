/** Telegram administration wire types. The bot token is write-only (masked hint only). */
import type { TelegramHealth } from './strategy43';

export type TelegramEvent = 'NEW' | 'TP1' | 'TP2' | 'TP3' | 'STOPPED' | 'EXPIRED';

export interface TelegramRecipient {
  id: number;
  name: string;
  chat_id: string;
  enabled: boolean;
  buy: boolean;
  sell: boolean;
  timeframes: string[];
  symbols: string[];
  lifecycle: boolean;
}

export type TelegramRecipientInput = Partial<Omit<TelegramRecipient, 'id'>>;

export interface TelegramSettings {
  configured: boolean;
  token_hint: string;
  bot_username: string | null;
  enabled: boolean;
  events: Record<TelegramEvent, boolean>;
  status: string;
  status_detail: string;
  checked_at: string | null;
  recipients: TelegramRecipient[];
  health?: TelegramHealth;
}

export interface TelegramDelivery {
  id: number;
  signal_id: string;
  recipient_id: number;
  recipient: string;
  event: string;
  symbol: string;
  timeframe: string;
  status: 'pending' | 'sent' | 'failed' | 'skipped';
  attempts: number;
  error: string;
  test: boolean;
  created_at: string;
  sent_at: string | null;
}

export interface TelegramChat {
  chat_id: string;
  type: string;
  title: string;
}

export interface TelegramTestResult {
  recipient_id: number;
  name: string;
  ok: boolean;
  message_id?: number;
  error?: string;
}
