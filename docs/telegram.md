# Telegram notifications (v1.2)

Wese Trade sends every **confirmed** BUY / SELL to Telegram. This covers:
- Strategy 4.3 on 15m / 30m / 1h;
- execution confirmations on 1m / 5m / 10m.

Each message is built from the **same canonical persisted signal** the application shows;
Telegram never computes its own levels. The scanner's ranking updates are never sent.

## Message

Every message includes:
- the symbol and the side (BUY — شراء / SELL — بيع);
- the primary timeframe, plus the entry-timing timeframe for 1m / 5m / 10m confirmations;
- the quality tier (e.g. «A — قوية»);
- «قوة الإشارة» out of 100, plus «قوة توقيت الدخول» for execution confirmations;
- the setup type;
- the entry, SL and TP1 / TP2 / TP3, and the R:R;
- the signal time in UTC.

Fixture messages from the admin page start with «🧪 TEST».

## Events

| Event | Default |
|---|---|
| NEW BUY / SELL | on |
| TP1 / TP2 / TP3 | on |
| STOPPED | on |
| EXPIRED (no entry) | off |

Each recipient has its own filters:
- enabled;
- BUY;
- SELL;
- timeframes (empty = all);
- symbols (empty = all);
- lifecycle alerts (TP / SL / expiry).

## Guarantees

- **Deduplication:** one delivery row per (signal id, recipient, event), enforced by a unique
  constraint. Replays, reconnects and restarts never resend an alert. After a restart, a
  pending alert older than 2 hours is marked "not sent" instead of being sent late.
- **Isolation:** the signal engine only enqueues and never waits for the network. Failures
  never reach the engine.
  - Delivery uses bounded retries with backoff: 5 attempts at 2 / 4 / 8 / 16 / 32 s, and
    Telegram's own `retry_after` is respected on HTTP 429.
  - Failures are kept in the delivery log, and the health status shows the last error.
- **Secrets:**
  - The bot token is write-only. It is validated with `getMe`, then stored sealed in the
    local database (HMAC-SHA256 encrypt-then-MAC, with a key derived from the installation
    secret).
  - Only a masked hint is ever returned (e.g. `••••AbCd`), and the token is redacted from
    every error and log line.
  - It is never committed to the repository.

## Setup (admin → الإعدادات → تنبيهات Telegram)

1. In Telegram, open **@BotFather**, send `/newbot`, and choose a name and a username ending
   in `bot`.
2. Copy the token BotFather sends (`123456789:AA…`) and paste it into «رمز البوت».
   «حفظ والتحقق» checks it with Telegram.
3. Open a chat with your new bot, press **Start**, and send any message. For a group, add
   the bot to the group and send a message there.
4. Press «البحث عن Chat ID» and pick the chat (or type the id: a personal id is a number;
   group / channel ids start with `-100`). Give it a display name and press «إضافة».
5. Use «رسالة اختبار», then «إشارة TEST — BUY / SELL», to verify delivery.

## API (admin only)

`/api/v1/telegram` supports:

| Method | Path | Purpose |
|---|---|---|
| GET | `` | settings and health |
| PUT / DELETE | `/token` | set or remove the bot token |
| POST | `/test-connection` | check the connection with Telegram |
| PATCH | `/options` | enable notifications and choose events |
| POST | `/test-message` | send a plain test message |
| POST | `/test-signal` | send a TEST BUY / SELL fixture |
| GET | `/chats` | find chat ids |
| POST / PATCH / DELETE | `/recipients` | manage recipients |
| GET | `/deliveries` | the delivery log |
