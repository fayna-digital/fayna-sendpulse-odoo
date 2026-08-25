# Fayna Channel Bridge

Власний транспортний шар для DM-каналів Odoo (резерв до SendPulse).

## Статус

**M0** — каркас модуля + модель channel.backend + Telegram пілот.
**M1** — real auto-failover (SendPulse healthcheck + перемикання transport_priority).
**M2** — Meta (IG, Messenger) send через наявні page токени + Messenger webhook (verify + POST).
**M3** — Viber, WhatsApp Cloud, TikTok, LiveChat send + webhook.

## Структура

```
fayna_channel_bridge/
├── __manifest__.py
├── controllers/
│   ├── __init__.py
│   └── main.py                 # Telegram webhook (/bridge/telegram/webhook/<token>)
├── models/
│   ├── __init__.py
│   ├── channel_backend.py      # модель "підключений канал"
│   ├── channel_message.py      # журнал повідомлень + ідемпотентність
│   ├── sendpulse_connect.py    # _inherit: transport + _send_single_message branching
│   └── mail_channel.py         # _inherit: маршрутизація вихідних
├── security/
│   ├── security.xml
│   └── ir.model.access.csv
├── data/
│   └── channel_backend_cron.xml
├── views/
│   └── channel_backend_views.xml
├── tests/
│   └── test_telegram_webhook.py
├── Dockerfile.test
├── docker-compose.test.yml
└── README.md
```

## Docker-тестування

Модуль тестується в ізольованому Odoo 17 середовищу через Docker.

```bash
# 1. Запустити тестове середовище (підниме Odoo + PostgreSQL, інсталює модули)
docker compose -f docker-compose.test.yml up

# 2. Запустити тести
docker compose -f docker-compose.test.yml exec web pytest

# 3. Зупинити і прибрати
docker compose -f docker-compose.test.yml down
```

> **Важливо:** `docker-compose.test.yml` монтує `../` як `extra-addons`, тобто
> очікує, що `odoo_chatwoot_connector` (базовий модуль, `depends`) лежить
> сусідно в тому ж каталогу. В реальному деплою CampScout він уже присутній
> в `addons_path`.

## Локальний lint (ruff)

```bash
ruff check fayna_channel_bridge/
ruff format fayna_channel_bridge/
```

## Конфигурація

Канали керуються через меню **Channel Bridge → Канали** (модель `channel.backend`):

- `service` — канал (telegram/instagram/facebook/messenger/viber/whatsapp/tiktok/livechat)
- `provider` — `direct` (власний) або `sendpulse` (для майбутньої міграції)
- `transport_priority` — `own` / `sendpulse` / `auto`
- `bot_token` — Telegram Bot Token (encrypted)
- `heal_url` — webhook URL (авто-заполнюється при `register_telegram_webhook`)

## Telegram webhook

Реєстрация: `POST https://api.telegram.org/bot<TOKEN>/setWebhook` →
`https://<odoo>/bridge/telegram/webhook/<TOKEN>`.

Прийом: `POST /bridge/telegram/webhook/<token>` — токен у URL є аутентифікацією.
Payload нормалізується до загальної структури і передається в
`sendpulse.connect._process_incoming_event` (той самий обробник, що й для SendPulse).

## Ідемпотентність

`channel.message` має partial unique index на
`(provider_message_id, service, direction='incoming')` — повторний webhook
не дублює повідомлення.

## Транспорт

`sendpulse.connect.transport`:
- `sendpulse` — поточний шлях (за замовчуванням)
- `own` — власний транспорт через `channel.backend`
- `auto` — спершу SendPulse, при помилці fallback на власний
