# Fayna Channel Bridge

Власний прямий транспортний шар для DM-каналів Odoo (без зовнішнього посередника).

## Статус

**M0** — каркас модуля + модель channel.backend + Telegram пілот.
**M1** — real auto-failover (healthcheck + перемикання transport_priority).
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
│   ├── channel_conversation.py # автономна модель розмов + receive handler
│   ├── channel_message.py      # журнал повідомлень + ідемпотентність
│   └── mail_channel.py         # _inherit: маршрутизація вихідних
├── security/
│   ├── security.xml
│   └── ir.model.access.csv
├── data/
│   └── channel_backend_cron.xml
├── views/
│   └── channel_backend_views.xml
├── tests/
│   ├── test_telegram_webhook.py
│   └── test_archive_feature.py
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

> **Важливо:** `fayna_channel_bridge` — повністю автономний модуль (без
> зовнішнього базового модуля). `docker-compose.test.yml` монтує лише цей
> каталог як `extra-addons`; залежності — штатні `mail` та `web`.

## Локальний lint (ruff)

```bash
ruff check fayna_channel_bridge/
ruff format fayna_channel_bridge/
```

## Конфигурація

Канали керуються через меню **Channel Bridge → Канали** (модель `channel.backend`):

- `service` — канал (telegram/instagram/facebook/messenger/viber/whatsapp/tiktok/livechat)
- `provider` — `direct` (власний транспорт)
- `transport_priority` — `own` / `auto`
- `bot_token` — Telegram Bot Token (encrypted)
- `heal_url` — webhook URL (авто-заповнюється при `register_telegram_webhook`)

## Telegram webhook

Реєстрація: `POST https://api.telegram.org/bot<TOKEN>/setWebhook` →
`https://<odoo>/bridge/telegram/webhook/<TOKEN>`.

Прийом: `POST /bridge/telegram/webhook/<token>` — токен у URL є аутентифікацією.
Payload нормалізується до загальної структури і передається в
`channel.conversation._process_incoming_event` (власний обробник вхідних).

## Ідемпотентність

`channel.message` має partial unique index на
`(provider_message_id, service, direction='incoming')` — повторний webhook
не дублює повідомлення.

## Транспорт

`channel.conversation.transport`:
- `own` — власний транспорт через `channel.backend`
- `auto` — спершу власний, при помилці fallback

## Архів розмов

`channel.conversation` підтримує архівацію старих розмов через нативний
механізм Odoo (`active`). Cron `cron_archive_old_conversations` стискає
розмови старші за налаштований період (за замовчуванням 30 днів),
зберігаючи історію переписок без видалення даних.
