# Fayna SendPulse Odo

![Odoo Version](https://img.shields.io/badge/Odoo-17.0-purple)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Graph API](https://img.shields.io/badge/Meta%20Graph-v25.0-1877F2)
![Module Version](https://img.shields.io/badge/Module-17.0.3.7.1-brightgreen)
![License](https://img.shields.io/badge/License-LGPL--3.0-green.svg)
![Status](https://img.shields.io/badge/Status-Production-brightgreen)

**Двостороння інтеграція SendPulse ↔ Odoo з автоматичними відповідями на коментарі FB/IG і LLM-класифікацією.**

Developed by [Fayna Digital](https://fayna.agency) — Volodymyr Shevchenko.

---

## Зміст

- [Можливості](#можливості)
- [Архітектура (коротко)](#архітектура-коротко)
- [Швидкий старт](#швидкий-старт)
- [Налаштування](#налаштування)
- [Структура модуля](#структура-модуля)
- [Технічна документація](#технічна-документація)
- [Ліцензія](#ліцензія)

---

## Можливості

### 📨 Діалоги з клієнтами (core)

- Webhook-прийом повідомлень з SendPulse (Telegram, Instagram, Facebook, Messenger, Viber, WhatsApp, LiveChat, TikTok)
- Двостороннє спілкування через Odoo Discuss — оператор відповідає з картки, клієнт отримує у месенджері
- Автоматична ідентифікація клієнта по email/phone/bot-змінних → прив'язка до `res.partner`
- Queue-based pickup — оператор сам забирає чат з черги «Новий» / «Нове повідомлення»
- Підтримка вкладень (фото, файли, аудіо, відео)
- UTM-атрибуція першого контакту по каналу
- Відновлення втрачених webhook-ів (cron `cron_pull_missing_contacts`)
- Авто-привітання нового контакту (2 налаштовуваних повідомлення)
- Архів переписки у вкладці **Messaging** картки партнера

### 💬 Коментарі FB / Instagram (v17.0.3.x)

- Обробка webhook-подій `incoming_message` з `comment_id` (FB post/reel + IG feed)
- **Multi-page routing** — резолвінг сторінки за `page_id` з webhook, кожна відповідає зі свого Page Token
- **Публічна відповідь** під коментарем через Meta Graph API (Graph v25.0): ротація з 5 шаблонів per-post
- **Приватна відповідь** у Messenger / IG Direct (`/private_replies`, `/{ig-user-id}/messages`)
- **LLM-класифікатор** (Anthropic Claude Haiku, 8 категорій): thanks / complaint / spam / question_price / dates / age / general / other
- Маршрутизація за категорією: thanks → no reply, spam → auto-hide через Graph API, complaint → Telegram-алерт менеджерам
- Self-loop guard — не відповідаємо на власні коментарі з Page/IG Business акаунта
- Per-post dedup і per-contact single-shot для приватного повідомлення

### 🛡 Надійність (v17.0.3.x)

- **Exponential backoff retry** на Graph API (1s / 3s / 9s) для 5xx / 429 / network errors
- **Audit log** усіх Graph API викликів у `ir.logging` (`name=odoo_chatwoot_connector.fb_api`)
- **PostgreSQL advisory lock** на `(contact_id, service)` і `comment_id` — захист від race condition при конкурентних webhook-ах
- **Messenger 24h window tracking** — поле `sp_messenger_window_expires_at`, cron-алерт за 2h до закриття
- **Weekly token check** (`cron_check_fb_token_expiry`) — для всіх Page-ів + legacy
- **Token expiry precision** — через `/debug_token` з app_id + app_secret (точний `days_left`)

### 📊 Analytics / CRM

- **Funnel metrics** — 7-стадійний pipeline: `comment_only → private_sent → customer_replied → operator_engaged → lead_created → closed_won | closed_lost`
- **SLA метрика** — `sp_first_reply_time_sec` (computed, stored): секунди між першим inbound і першою відповіддю оператора
- Link до `crm.lead` через `sp_lead_id` (Many2one)
- `sp_comment_category` для аналітики розподілу коментарів

### 🔔 Telegram-алерти

- Бот ескалації менеджерам (наприклад `@csodooalerts_bot` → group CampScout.team)
- 🚨 Скарги під постами (негайно)
- 🚫 Прихований спам (silent)
- ⏳ Закриття 24h вікна за 2h (silent)
- ⚠️ FB Page Token недійсний / термін ≤ 7 днів

---

## Архітектура (коротко)

```
   ┌──────────────────────────┐            ┌──────────────────────────┐
   │   SendPulse (webhook)    │            │      Meta Graph API      │
   │  Telegram/IG/FB/WA/Viber │            │     (coments+messages)    │
   └────────────┬─────────────┘            └──────────────▲───────────┘
                │ POST /sendpulse/webhook                  │
                ▼                                          │
       controllers/main.py                                 │
         (token-verified, async-friendly, idempotent)      │
                │                                          │
                ▼                                          │
       sendpulse.webhook.data                              │
         (raw JSON audit, 7-day retention)                 │
                │                                          │
                ▼                                          │
       sendpulse.connect._process_incoming_event           │
         ├─ is_comment? ─▶ _process_comment_event ─────────┤
         │                   ├─ advisory_lock(comment_id)  │
         │                   ├─ resolve sendpulse.facebook.page
         │                   ├─ self-loop guard
         │                   ├─ LLM classify (Anthropic Haiku)
         │                   ├─ route: thanks/spam/complaint/question_*
         │                   ├─ public reply ──────────────┤ Graph v25.0
         │                   ├─ private reply ─────────────┤
         │                   └─ hide_comment (if spam) ────┤
         │
         └─ inbound ─▶ advisory_lock(contact_id|service)
                       ├─ find partner (email/phone/vars)
                       ├─ get/create sendpulse.connect
                       ├─ create discuss.channel (manual pickup)
                       └─ post mail.message into channel
                              │
                              ▼
                       mail_channel.py override
                              │ (if operator replies)
                              ▼
                  SendPulse REST API ──▶ клієнт у месенджері
```

Детальна архітектура з усіма flow та моделями: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Швидкий старт

### Вимоги

- Odoo **17.0** (Community або Enterprise)
- Python **3.10+**, пакет `requests`
- Odoo модулі: `mail`, `contacts`, `crm`, `web`
- (Опціонально для LLM): Anthropic API key, `console.anthropic.com`
- (Опціонально для Telegram-алертів): Telegram Bot Token, Chat ID

### Встановлення

```bash
cd /path/to/odoo/custom-addons
git clone git@github.com:VladSh77/fayna-sendpulse-odoo.git odoo_chatwoot_connector
docker exec <odoo_web_container> /usr/bin/odoo -d <db> --stop-after-init --no-http -i odoo_chatwoot_connector
docker compose restart web
```

Або через UI: **Settings → Apps** → пошук «**Fayna SendPulse Odo**» → Install.

### Upgrade

Детальна процедура: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Коротко:

```bash
# На сервері
cd /opt/campscout/custom-addons/odoo_chatwoot_connector
git pull
docker exec <odoo_web> /usr/bin/odoo -d <db> --stop-after-init --no-http -u odoo_chatwoot_connector
docker compose restart web
```

---

## Налаштування

Повний reference усіх полів: [docs/CONFIGURATION.md](docs/CONFIGURATION.md). Тут — коротко.

### 1. SendPulse API

`SendPulse → Налаштування`:

| Поле | Джерело | Обов'язкове |
|---|---|---|
| SendPulse Client ID | SendPulse → Profile → Settings → API | ✅ |
| SendPulse Client Secret | там же (Show) | ✅ |
| Webhook Secret Token | довільний рядок (HMAC) | ✅ |
| Webhook URL | **генерується автоматично** (readonly) | — |

### 2. Webhook у SendPulse

Chatbots → Bot → Settings → Webhooks → `+ Add Webhook`.

URL: значення з поля *Webhook URL* в Odoo.

Events (відмітити): ✅ subscribed / ✅ incoming_message / ✅ open_chat / ✅ unsubscribed.

### 3. Facebook Pages (multi-page, опціонально)

Меню **SendPulse → Facebook Pages** або через Settings → **Синхронізувати з Meta /me/accounts** (потрібен короткоживучий **User Access Token** з Graph API Explorer з правами `pages_show_list` + `business_management`).

Метод автоматично створює `sendpulse.facebook.page` записи для всіх сторінок де користувач — адмін, з їхніми Page Tokens і приєднаними IG Business акаунтами. Одна сторінка має бути відмічена як `is_default`.

### 4. LLM-класифікатор (опціонально)

| Поле | Значення |
|---|---|
| `llm_classifier_enabled` | True |
| `anthropic_api_key` | `sk-ant-api03-...` |
| `llm_model` | `claude-haiku-4-5` |
| `sp_comment_hide_spam_enabled` | True |

Вартість: ~**$0.15 за 1000 коментарів** на Claude Haiku 4.5. Без налаштування — коментарі не класифікуються, відповідь відправляється завжди.

### 5. Telegram-алерти (опціонально)

| Поле | Значення |
|---|---|
| `telegram_alerts_enabled` | True |
| `telegram_bot_token` | `BOT_TOKEN` з @BotFather |
| `telegram_chat_id` | ID групи (negative для supergroup) |

### 6. FB App credentials (для `debug_token`)

Потрібні щоб точно знати коли помре Page Token (інакше cron каже «живий», але не `days_left`).

Джерело: developers.facebook.com → Apps → Campscout_odoo → Settings → Basic.

### 7. Права доступу

`Settings → Users → user → SendPulse Odo`:

- **SendPulse Odo / Officer** — бачить і веде свої розмови
- **SendPulse Odo / Administrator** — бачить усі + керує Pages + може ручно перевіряти токени

---

## Структура модуля

```
sendpulse-odoo/
├── __manifest__.py                  — метадата модуля (v17.0.3.7.1)
├── README.md                        — цей файл
├── CHANGELOG.md                     — журнал змін
├── TECHNICAL_DOCS.md                — технічний reference
├── LICENSE                          — LGPL-3.0
│
├── controllers/
│   └── main.py                      — POST /sendpulse/webhook
│
├── models/
│   ├── sendpulse_connect.py         — центральна модель розмови (2600+ рядків)
│   ├── sendpulse_message.py         — message + partner archive + channel registry
│   ├── sendpulse_facebook_page.py   — multi-page FB/IG (v17.0.3.7.0)
│   ├── sendpulse_identify_wizard.py — wizard для ручної ідентифікації
│   ├── res_config_settings.py       — Settings UI fields
│   ├── res_partner.py               — розширення партнера
│   └── mail_channel.py              — override message_post → SendPulse API
│
├── views/
│   ├── sendpulse_connect_views.xml         — list/form/settings
│   ├── sendpulse_facebook_page_views.xml   — Facebook Pages UI
│   ├── sendpulse_identify_wizard_views.xml — identify wizard
│   ├── res_partner_views.xml               — розширення картки партнера
│   └── res_config_settings_views.xml       — Settings inheritance
│
├── static/src/
│   ├── thread_patch.js                     — patch Thread моделі (OWL)
│   ├── sendpulse_thread_actions.js         — реєстрація дії в threadActionsRegistry
│   └── components/sendpulse_info_panel/    — OWL компонент панелі
│
├── data/
│   ├── sendpulse_data.xml                  — початкові дані (групи, menu, templates)
│   ├── sendpulse_utm_data.xml              — UTM джерела для соцмереж
│   └── clean_data_cron.xml                 — cron: cleanup, token check, 24h window
│
├── security/
│   ├── security.xml                        — групи (Officer / Admin) + record rules
│   └── ir.model.access.csv                 — acl для всіх моделей
│
├── tests/
│   └── test_*.py                           — unit tests
│
└── docs/
    ├── ARCHITECTURE.md                     — повна архітектура + flows
    ├── CONFIGURATION.md                    — reference усіх settings/cron/permissions
    ├── DEPLOYMENT.md                       — install/upgrade/rollback
    ├── TZ.md                               — umbrella технічне завдання
    ├── TZ_COMMENT_AUTOREPLY.md             — ТЗ на відповіді на коменти (v1.4)
    └── CRITICAL_INCIDENT_*.md              — постмортеми інцидентів
```

### Моделі даних

| Модель | Тип | Призначення |
|---|---|---|
| `sendpulse.connect` | Model | Центральна розмова (один запис на клієнта+канал або на коментар) |
| `sendpulse.message` | Model | Повідомлення розмови (linked на `sendpulse.connect`) |
| `sendpulse.facebook.page` | Model | FB Page + Page Token + IG Business ID + per-page URL overrides |
| `partner.sendpulse.channel` | Model | Соціальні канали на картці партнера |
| `partner.sendpulse.message` | Model | Архів переписки під партнером |
| `sendpulse.webhook.data` | Model | Raw webhook JSON (7-day retention через cron) |
| `sendpulse.identify.wizard` | TransientModel | Wizard ідентифікації партнера |
| `res.config.settings` (inherit) | TransientModel | Всі Settings поля модуля |
| `discuss.channel` (inherit) | Model | Додано `sendpulse_connect_id` М2О |

---

## Технічна документація

| Документ | Призначення |
|---|---|
| [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md) | Authoritative technical reference |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture + data flows |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Усі налаштування (Settings UI + `ir.config_parameter`) |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Install / upgrade / rollback procedures |
| [docs/TZ.md](docs/TZ.md) | Umbrella технічне завдання + roadmap |
| [docs/TZ_COMMENT_AUTOREPLY.md](docs/TZ_COMMENT_AUTOREPLY.md) | ТЗ на автовідповіді на коменти (v1.4) |
| [CHANGELOG.md](CHANGELOG.md) | Релізний журнал (semver patch-rev) |

### Правила межі модуля

**⚠️ Зміни в SendPulse лише за окремим ТЗ.** Інтеграція з Discuss/Omnichannel — у окремому модулі `omnichannel_bridge`. Порушення фіксуються у `docs/CRITICAL_INCIDENT_*.md` та LOG.md.

---

## Ліцензія

[LGPL-3.0](LICENSE)

---

*Розроблено для [CampScout](https://campscout.eu) — платформи організації дитячих таборів.*
