import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Send, Trash2 } from 'lucide-react';
import { type SubmitEvent, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { TELEGRAM_STATE_AR } from '@/features/strategy43/labels';
import { ApiError } from '@/lib/http';
import { telegramApi } from '@/services/api/telegram';
import type { TelegramEvent, TelegramRecipient, TelegramRecipientInput } from '@/types/telegram';

import { Section } from './Section';

const input = 'border-line bg-sunken h-9 rounded-md border px-2 text-sm';
const TIMEFRAMES = ['1m', '5m', '10m', '15m', '30m', '1h'] as const;
const EVENTS: { key: TelegramEvent; label: string }[] = [
  { key: 'NEW', label: 'إشارة جديدة BUY / SELL' },
  { key: 'TP1', label: 'تحقق الهدف 1' },
  { key: 'TP2', label: 'تحقق الهدف 2' },
  { key: 'TP3', label: 'تحقق الهدف 3' },
  { key: 'STOPPED', label: 'ضُرب وقف الخسارة' },
  { key: 'EXPIRED', label: 'انتهاء الصلاحية' },
];
const DELIVERY_AR: Record<string, string> = {
  sent: 'أُرسلت',
  pending: 'قيد الإرسال',
  failed: 'فشلت',
  skipped: 'لم تُرسل',
};

function message(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'network_error') return 'تعذر الاتصال بالخادم المحلي.';
    return e.code;
  }
  return 'حدث خطأ غير متوقع.';
}

function useInvalidate() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ['telegram'] });
  };
}

function Check({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-center gap-1.5 text-xs">
      <input
        type="checkbox"
        className="accent-[var(--ns-accent)]"
        checked={checked}
        disabled={disabled}
        onChange={(e) => {
          onChange(e.target.checked);
        }}
      />
      {label}
    </label>
  );
}

function RecipientRow({ r }: { r: TelegramRecipient }) {
  const invalidate = useInvalidate();
  const [error, setError] = useState<string | null>(null);
  const [symbols, setSymbols] = useState(r.symbols.join(', '));
  const update = useMutation({
    mutationFn: (body: TelegramRecipientInput) => telegramApi.updateRecipient(r.id, body),
    onSuccess: () => {
      setError(null);
      invalidate();
    },
    onError: (e) => {
      setError(message(e));
    },
  });
  const remove = useMutation({
    mutationFn: () => telegramApi.deleteRecipient(r.id),
    onSuccess: invalidate,
    onError: (e) => {
      setError(message(e));
    },
  });
  const test = useMutation({
    mutationFn: () => telegramApi.sendTestMessage(r.id),
    onSuccess: (res) => {
      setError(res[0]?.ok ? 'تم إرسال رسالة الاختبار ✅' : (res[0]?.error ?? 'فشل الإرسال'));
    },
    onError: (e) => {
      setError(message(e));
    },
  });
  const toggleTf = (tf: string) => {
    const all = r.timeframes.length === 0 ? [...TIMEFRAMES] : r.timeframes;
    const next = all.includes(tf) ? all.filter((x) => x !== tf) : [...all, tf];
    update.mutate({ timeframes: next.length === TIMEFRAMES.length ? [] : next });
  };
  return (
    <li className="border-line/60 border-t py-2" data-testid={`recipient-${String(r.id)}`}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{r.name}</span>
        <span className="ns-ltr text-fg-subtle text-xs">{r.chat_id}</span>
        {!r.enabled && <span className="text-bear text-2xs">معطّل</span>}
        <div className="ms-auto flex items-center gap-1">
          <Button
            variant="ghost"
            disabled={test.isPending || !r.enabled}
            onClick={() => {
              test.mutate();
            }}
          >
            اختبار
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              update.mutate({ enabled: !r.enabled });
            }}
          >
            {r.enabled ? 'تعطيل' : 'تفعيل'}
          </Button>
          <Button
            variant="ghost"
            aria-label={`حذف ${r.name}`}
            onClick={() => {
              if (window.confirm(`حذف المستلم ${r.name}؟`)) remove.mutate();
            }}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-3">
        <Check
          label="BUY"
          checked={r.buy}
          onChange={(v) => {
            update.mutate({ buy: v });
          }}
        />
        <Check
          label="SELL"
          checked={r.sell}
          onChange={(v) => {
            update.mutate({ sell: v });
          }}
        />
        <Check
          label="تنبيهات المتابعة (TP / SL)"
          checked={r.lifecycle}
          onChange={(v) => {
            update.mutate({ lifecycle: v });
          }}
        />
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1" aria-label="الفريمات">
        {TIMEFRAMES.map((tf) => {
          const on = r.timeframes.length === 0 || r.timeframes.includes(tf);
          return (
            <button
              key={tf}
              type="button"
              aria-pressed={on}
              onClick={() => {
                toggleTf(tf);
              }}
              className={`ns-ltr text-2xs rounded border px-1.5 py-0.5 ${
                on ? 'border-accent/50 bg-accent/10 text-accent' : 'border-line text-fg-subtle'
              }`}
            >
              {tf}
            </button>
          );
        })}
        <input
          dir="ltr"
          aria-label={`عملات ${r.name}`}
          placeholder="كل العملات (أو BTCUSDT, ETHUSDT)"
          className={`${input} h-7 min-w-40 flex-1 text-xs`}
          value={symbols}
          onChange={(e) => {
            setSymbols(e.target.value);
          }}
          onBlur={() => {
            const list = symbols
              .split(/[,\s]+/)
              .map((x) => x.trim().toUpperCase())
              .filter(Boolean);
            if (list.join(',') !== r.symbols.join(',')) update.mutate({ symbols: list });
          }}
        />
      </div>
      {error && <p className="text-fg-muted text-2xs mt-1">{error}</p>}
    </li>
  );
}

/**
 * Telegram notifications (administrators). The bot token is write-only: after saving, only
 * a masked hint is ever shown, it is stored encrypted, and it never appears in logs.
 */
export function TelegramSection() {
  const invalidate = useInvalidate();
  const { data, isError } = useQuery({
    queryKey: ['telegram', 'settings'],
    queryFn: ({ signal }) => telegramApi.settings(signal),
    refetchInterval: 30_000,
  });
  const log = useQuery({
    queryKey: ['telegram', 'deliveries'],
    queryFn: ({ signal }) => telegramApi.deliveries(10, signal),
    refetchInterval: 30_000,
  });
  const [token, setToken] = useState('');
  const [name, setName] = useState('');
  const [chatId, setChatId] = useState('');
  const [note, setNote] = useState<string | null>(null);
  const done = (text: string) => () => {
    setNote(text);
    invalidate();
  };
  const fail = (e: unknown) => {
    setNote(message(e));
  };
  const saveToken = useMutation({
    mutationFn: () => telegramApi.setToken(token),
    onSuccess: () => {
      setToken('');
      done('تم حفظ رمز البوت والتحقق منه ✅')();
    },
    onError: fail,
  });
  const clear = useMutation({
    mutationFn: () => telegramApi.clearToken(),
    onSuccess: done('تم حذف رمز البوت.'),
    onError: fail,
  });
  const check = useMutation({
    mutationFn: () => telegramApi.testConnection(),
    onSuccess: (s) => {
      done(s.status === 'connected' ? 'الاتصال سليم ✅' : `فشل الاتصال: ${s.status_detail}`)();
    },
    onError: fail,
  });
  const options = useMutation({
    mutationFn: (body: Parameters<typeof telegramApi.setOptions>[0]) =>
      telegramApi.setOptions(body),
    onSuccess: invalidate,
    onError: fail,
  });
  const add = useMutation({
    mutationFn: () => telegramApi.addRecipient({ name: name.trim(), chat_id: chatId.trim() }),
    onSuccess: () => {
      setName('');
      setChatId('');
      done('تمت إضافة المستلم.')();
    },
    onError: fail,
  });
  const chats = useMutation({ mutationFn: () => telegramApi.chats(), onError: fail });
  const testAll = useMutation({
    mutationFn: () => telegramApi.sendTestMessage(),
    onSuccess: (res) => {
      done(
        res.length === 0
          ? 'لا يوجد مستلمون مفعّلون.'
          : res.map((x) => `${x.name}: ${x.ok ? '✅' : `❌ ${x.error ?? ''}`}`).join(' · '),
      )();
    },
    onError: fail,
  });
  const fixture = useMutation({
    mutationFn: (side: 'BUY' | 'SELL') => telegramApi.sendTestSignal(side),
    onSuccess: (r) => {
      done(`تم إرسال إشارة TEST إلى ${String(r.deliveries.length)} مستلم.`)();
    },
    onError: fail,
  });
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    add.mutate();
  };
  const status = data
    ? (TELEGRAM_STATE_AR[data.health?.state ?? data.status] ?? data.status)
    : '--';
  return (
    <Section id="telegram" title="تنبيهات Telegram">
      {isError || !data ? (
        <p className="text-fg-subtle text-xs">{isError ? 'تعذر تحميل الإعدادات.' : '…'}</p>
      ) : (
        <div className="flex flex-col gap-3" data-testid="telegram-section">
          <div className="text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-fg-subtle text-xs">حالة البوت</span>
              <span data-testid="telegram-status" className="font-medium">
                {status}
              </span>
              {data.bot_username && (
                <span className="ns-ltr text-fg-muted text-xs">@{data.bot_username}</span>
              )}
              {data.token_hint && (
                <span className="ns-ltr text-fg-subtle text-2xs">{data.token_hint}</span>
              )}
            </div>
            {data.status_detail && (
              <p className="text-warning text-2xs mt-0.5">{data.status_detail}</p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              dir="ltr"
              type="password"
              autoComplete="off"
              aria-label="رمز البوت (Bot Token)"
              placeholder={data.configured ? 'رمز جديد لاستبدال الحالي' : 'Bot Token من @BotFather'}
              className={`${input} min-w-56 flex-1`}
              value={token}
              onChange={(e) => {
                setToken(e.target.value);
              }}
            />
            <Button
              disabled={token.trim().length < 20 || saveToken.isPending}
              onClick={() => {
                saveToken.mutate();
              }}
            >
              حفظ والتحقق
            </Button>
            {data.configured && (
              <>
                <Button
                  variant="ghost"
                  disabled={check.isPending}
                  onClick={() => {
                    check.mutate();
                  }}
                >
                  اختبار الاتصال
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    if (window.confirm('حذف رمز البوت؟ ستتوقف التنبيهات.')) clear.mutate();
                  }}
                >
                  حذف الرمز
                </Button>
              </>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Check
              label="تفعيل التنبيهات"
              checked={data.enabled}
              onChange={(v) => {
                options.mutate({ enabled: v });
              }}
            />
            {EVENTS.map((ev) => (
              <Check
                key={ev.key}
                label={ev.label}
                checked={data.events[ev.key]}
                onChange={(v) => {
                  options.mutate({ events: { [ev.key]: v } });
                }}
              />
            ))}
          </div>

          <div>
            <h3 className="text-xs font-semibold">المستلمون</h3>
            <ul data-testid="telegram-recipients">
              {data.recipients.map((r) => (
                <RecipientRow key={r.id} r={r} />
              ))}
            </ul>
            <form
              onSubmit={submit}
              className="border-line mt-2 flex flex-wrap items-end gap-2 border-t pt-2"
            >
              <input
                aria-label="اسم المستلم"
                placeholder="الاسم"
                className={`${input} w-32`}
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                }}
              />
              <input
                dir="ltr"
                aria-label="Chat ID"
                placeholder="Chat ID"
                className={`${input} w-40`}
                value={chatId}
                onChange={(e) => {
                  setChatId(e.target.value);
                }}
              />
              <Button type="submit" disabled={!name.trim() || !chatId.trim() || add.isPending}>
                إضافة
              </Button>
              {data.configured && (
                <Button
                  variant="ghost"
                  disabled={chats.isPending}
                  onClick={() => {
                    chats.mutate();
                  }}
                >
                  البحث عن Chat ID
                </Button>
              )}
            </form>
            {chats.data && (
              <ul className="text-2xs mt-1 flex flex-col gap-0.5" data-testid="telegram-chats">
                {chats.data.length === 0 && (
                  <li className="text-fg-subtle">
                    لم يُعثر على محادثات — أرسل أي رسالة إلى البوت أولاً ثم أعد المحاولة.
                  </li>
                )}
                {chats.data.map((c) => (
                  <li key={c.chat_id}>
                    <button
                      type="button"
                      className="hover:text-accent"
                      onClick={() => {
                        setChatId(c.chat_id);
                        if (!name) setName(c.title);
                      }}
                    >
                      <span className="ns-ltr">{c.chat_id}</span> — {c.title} ({c.type})
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {data.configured && (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="ghost"
                disabled={testAll.isPending}
                onClick={() => {
                  testAll.mutate();
                }}
              >
                <Send className="size-3.5" /> رسالة اختبار
              </Button>
              <Button
                variant="ghost"
                disabled={fixture.isPending}
                onClick={() => {
                  fixture.mutate('BUY');
                }}
              >
                إشارة TEST — BUY
              </Button>
              <Button
                variant="ghost"
                disabled={fixture.isPending}
                onClick={() => {
                  fixture.mutate('SELL');
                }}
              >
                إشارة TEST — SELL
              </Button>
            </div>
          )}
          {note && (
            <p className="text-fg-muted text-xs" role="status" data-testid="telegram-note">
              {note}
            </p>
          )}

          <div>
            <h3 className="text-xs font-semibold">سجل الإرسال</h3>
            <ul className="text-2xs mt-1 flex flex-col gap-0.5" data-testid="telegram-log">
              {(log.data ?? []).length === 0 && <li className="text-fg-subtle">لا يوجد بعد.</li>}
              {(log.data ?? []).map((d) => (
                <li key={d.id} className="flex flex-wrap gap-x-2" title={d.error}>
                  <span className="ns-ltr">{d.created_at.slice(0, 16).replace('T', ' ')}</span>
                  <span>{d.recipient}</span>
                  <span className="ns-ltr">
                    {d.symbol} {d.timeframe} {d.event}
                  </span>
                  {d.test && <span className="text-warning">TEST</span>}
                  <span className={d.status === 'failed' ? 'text-bear' : 'text-fg-muted'}>
                    {DELIVERY_AR[d.status] ?? d.status}
                    {d.attempts > 1 ? ` (${String(d.attempts)} محاولات)` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <details className="text-fg-subtle text-2xs">
            <summary className="cursor-pointer">كيف أحصل على رمز البوت و Chat ID؟</summary>
            <ol className="mt-1 list-decimal ps-5 leading-5">
              <li>افتح Telegram وابحث عن @BotFather ثم أرسل /newbot واتبع الخطوات.</li>
              <li>انسخ الرمز الذي يرسله BotFather (مثل 123456789:ABC…) والصقه أعلاه.</li>
              <li>افتح محادثة مع البوت الجديد واضغط Start وأرسل أي رسالة.</li>
              <li>اضغط «البحث عن Chat ID» واختر محادثتك — أو أضف البوت إلى مجموعة/قناة.</li>
              <li>استخدم «رسالة اختبار» للتأكد من وصول الرسائل.</li>
            </ol>
          </details>
        </div>
      )}
    </Section>
  );
}
