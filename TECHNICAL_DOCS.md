# Technical Documentation — Fayna SendPulse Odoo

**Module version:** `17.0.12.0` · **Last updated:** 2026-04-21
**Product:** Fayna Digital — [fayna.agency](https://fayna.agency)
**Author:** Volodymyr Shevchenko
**License:** LGPL-3.0

Authoritative technical reference модуля. Для архітектурних діаграм див. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Для налаштувань — [docs/CONFIGURATION.md](docs/CONFIGURATION.md). Для deploy — [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Зміст

1. [Огляд](#1-огляд)
2. [Структура коду](#2-структура-коду)
3. [Моделі даних — детально](#3-моделі-даних--детально)
4. [Webhook flow](#4-webhook-flow)
5. [SendPulse API інтеграція](#5-sendpulse-api-інтеграція)
6. [Meta Graph API інтеграція](#6-meta-graph-api-інтеграція)
7. [Anthropic LLM інтеграція](#7-anthropic-llm-інтеграція)
8. [Telegram Bot API інтеграція](#8-telegram-bot-api-інтеграція)
9. [Discuss інтеграція](#9-discuss-інтеграція)
10. [Cron tasks](#10-cron-tasks)
11. [Security & ACL](#11-security--acl)
12. [Migration notes](#12-migration-notes)
13. [Testing](#13-testing)

---

## 1. Огляд

**Призначення:** AI-first omnichannel рішення на базі Odoo — двостороння інтеграція SendPulse chatbots з Discuss, автоматична обробка коментарів FB/IG з LLM-класифікацією, AI-помічник оператора, lead-magnet flow (PDF/SMS-купон), live-awareness вільних місць у подіях, drip-кампанії, A/B публічні шаблони, авто-переклад UA↔PL.

**Технологічний стек:**
- **Odoo 17.0** (Community+)
- **Python 3.10+** (`requests`, `hashlib`, `markupsafe`)
- **PostgreSQL 14+** (advisory locks, partial unique indexes)
- **Meta Graph API v25.0** (FB + IG, multi-page через System User)
- **Anthropic Claude Haiku 4.5** (LLM classification + RAG + suggestions + translate)
- **Telegram Bot API** (escalation alerts, опц.)
- **TurboSMS** через `kw_sms_api` (SMS-купони, опц.)
- **Odoo `loyalty.program`** (shared coupon pool)
- **Odoo `event.event`** (live seats awareness)

**Зовнішні залежності:** `mail`, `contacts`, `crm`, `web` (Odoo core).

**Межа модуля:** тільки SendPulse ↔ Odoo. Omnichannel / ChatWoot / інші джерела — у окремому `omnichannel_bridge`. Див. §4 у [docs/TZ.md](docs/TZ.md).

---

## 2. Структура коду

```
sendpulse-odoo/                             # repo root
├── __init__.py                             # import controllers, models
├── __manifest__.py                         # metadata (version 17.0.3.7.1)
│
├── controllers/
│   ├── __init__.py
│   └── main.py                             # POST /sendpulse/webhook handler
│
├── models/
│   ├── __init__.py                         # import order важливий
│   ├── res_config_settings.py              # TransientModel, ~270 рядків
│   ├── sendpulse_message.py                # 3 моделі: message, partner_message, partner_channel
│   ├── sendpulse_facebook_page.py          # sendpulse.facebook.page (~135 рядків)
│   ├── sendpulse_connect.py                # ГОЛОВНА модель (~2600 рядків)
│   ├── sendpulse_identify_wizard.py        # TransientModel wizard
│   ├── mail_channel.py                     # override discuss.channel.message_post
│   └── res_partner.py                      # розширення картки партнера
│
├── views/                                  # XML views
├── security/                               # групи + ACL
├── data/                                   # XML seeds + cron
├── static/src/                             # OWL JS components
├── tests/                                  # unit tests
├── docs/                                   # документація
└── CHANGELOG.md                            # релізний журнал (semver patch-rev)
```

### 2.1 Import order (`models/__init__.py`)

```python
from . import res_config_settings          # 1. settings first (використовується іншими)
from . import sendpulse_message            # 2. message models
from . import sendpulse_facebook_page      # 3. multi-page (перед connect бо connect використовує)
from . import sendpulse_connect            # 4. головна модель
from . import sendpulse_identify_wizard    # 5. wizard
from . import mail_channel                 # 6. override discuss.channel
from . import res_partner                  # 7. розширення партнера
```

### 2.2 Manifest (`__manifest__.py`)

```python
{
    'name': 'Fayna SendPulse Odoo',
    'version': '17.0.3.7.1',
    'category': 'Discuss',
    'author': 'Fayna Digital — Volodymyr Shevchenko',
    'license': 'LGPL-3',
    'depends': ['mail', 'contacts', 'crm', 'web'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sendpulse_utm_data.xml',
        'data/sendpulse_data.xml',
        'data/clean_data_cron.xml',
        'views/sendpulse_connect_views.xml',
        'views/sendpulse_identify_wizard_views.xml',
        'views/sendpulse_facebook_page_views.xml',
        'views/res_partner_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_chatwoot_connector/static/src/thread_patch.js',
            'odoo_chatwoot_connector/static/src/components/sendpulse_info_panel/*.xml',
            'odoo_chatwoot_connector/static/src/components/sendpulse_info_panel/*.js',
            'odoo_chatwoot_connector/static/src/sendpulse_thread_actions.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
```

**⚠️ Папка на сервері = `odoo_chatwoot_connector`** (legacy ім'я, не міняти).

---

## 3. Моделі даних — детально

### 3.1 `sendpulse.connect` (головна модель розмови)

**Файл:** `models/sendpulse_connect.py`, ~2600 рядків. Центральна таблиця — одна розмова (або коментар) на запис.

#### Класові константи

```python
SERVICE_SELECTION = [
    ('telegram', 'Telegram'), ('instagram', 'Instagram'),
    ('facebook', 'Facebook'), ('messenger', 'Messenger'),
    ('viber', 'Viber'), ('whatsapp', 'WhatsApp'),
    ('livechat', 'LiveChat'), ('tiktok', 'TikTok'),
]

STAGE_SELECTION = [
    ('new', 'Новий'),
    ('in_progress', 'В роботі'),
    ('new_message', 'Нове повідомлення'),
    ('close', 'Закрито'),
]

_COMMENT_CATEGORIES = (
    'question_price', 'question_dates', 'question_age', 'question_general',
    'thanks', 'complaint', 'spam', 'other',
)
```

#### Поля (категорії)

| Група | Поля | Призначення |
|---|---|---|
| **Identity** | `name`, `partner_id`, `stage`, `service`, `sendpulse_contact_id` | Ідентифікація розмови |
| **Bot** | `bot_id`, `bot_name`, `social_username`, `social_profile_url` | Інформація про бота і соцмережі |
| **Unidentified** | `unidentified_email`, `unidentified_phone`, `is_unidentified` (computed) | Контакти що чекають ручну ідентифікацію |
| **Bot vars** | `sp_child_name`, `sp_booking_email`, `avatar_url`, `language_code`, `subscription_status` | Додаткові змінні з SendPulse |
| **Discuss** | `channel_id`, `message_ids`, `message_count`, `last_notified_at` | Зв'язок з Discuss каналом |
| **UTM** | `source_id` | Джерело першого контакту |
| **Comments** | `sp_is_comment`, `sp_comment_id`, `sp_comment_text`, `sp_post_id`, `sp_post_url`, `sp_page_id`, `sp_replied_public`, `sp_replied_private`, `sp_comment_category` | Коментарний flow |
| **24h window** | `sp_messenger_window_expires_at`, `sp_window_alert_sent` | Meta Messenger policy |
| **Funnel** | `sp_funnel_stage`, `sp_first_inbound_at`, `sp_first_reply_at`, `sp_first_reply_time_sec`, `sp_lead_id` | Analytics |
| **Computed** | `is_unidentified`, `service_icon`, `stage_sort` | UI helpers |

#### Ключові методи

| Метод | Тип | Призначення |
|---|---|---|
| `_process_incoming_event(data, contact, bot, service, event_type, ts)` | `@api.model` | Диспатчер вхідних webhook-подій |
| `_process_inbound(...)` | | DM flow |
| `_process_comment_event(...)` | `@api.model` | Comment flow |
| `_find_partner(contact_id, email, phone, variables)` | | Пошук партнера (3 пріоритети) |
| `_classify_comment(text, service)` | | LLM класифікація коментаря |
| `_fb_post_with_retry(url, payload, label, attempts, base_delay)` | | Graph API POST з retry |
| `_log_fb_audit(label, url, payload, status, response, attempts)` | | Аудит у ir.logging |
| `_get_fb_page_token(page=None)` | | Resolve Page Access Token з 4 пріоритетів |
| `_send_comment_public_reply(comment_id, service, text, page)` | | Публічна відповідь |
| `_send_comment_private_reply(comment_id, text, service, page)` | | Приватна відповідь |
| `_hide_comment(comment_id, service, page)` | | Приховати спам |
| `_notify_telegram(text, silent)` | `@api.model` | Telegram alert |
| `_create_discuss_channel(send_greeting)` | | Створення discuss.channel |
| `_send_autoreply_greeting(channel)` | | Авто-привітання |
| `action_open_discuss()` | | Відкриття чату + додавання оператора |
| `action_identify_partner()` | | Wizard ідентифікації |
| `action_close()` | | Закриття розмови |
| `send_message_to_sendpulse(text, attachment_url)` | | Відправка через SendPulse API |
| `cron_sync_discuss_channels()` | `@api.model` | Cron: відсутні канали |
| `cron_pull_missing_contacts()` | `@api.model` | Cron: втрачені webhook-и |
| `cron_check_fb_token_expiry()` | `@api.model` | Cron: перевірка токенів |
| `cron_check_messenger_windows()` | `@api.model` | Cron: 24h window alerts |
| `_check_single_fb_token(token, label)` | `@api.model` | Helper для cron |
| `_get_access_token(force_refresh)` | `@api.model` | SendPulse OAuth з cache |
| `_sendpulse_oauth_invalidate_cache()` | `@api.model` | Invalidate при 401 |

### 3.2 `sendpulse.facebook.page` (multi-page)

**Файл:** `models/sendpulse_facebook_page.py`

| Поле | Тип | Призначення |
|---|---|---|
| `name` | Char, required | Display name |
| `page_id` | Char, required, unique, indexed | FB Page ID |
| `access_token` | Char, required | Безстроковий Page Token |
| `ig_business_id` | Char | IG Business Account ID (якщо приєднаний) |
| `category` | Char | З /me/accounts |
| `active` | Boolean, default=True | Soft-delete |
| `is_default` | Boolean | Fallback (constraint: один у DB) |
| `last_checked_at` | Datetime | Оновлюється cron-ом |
| `token_status` | Char | Text від `_check_single_fb_token` |
| `landing_url` / `tg_url` / `yt_url` | Char | Per-page URL overrides |

**Методи:**
- `find_by_page_id(page_id)` — `@api.model`, lookup з fallback на default
- `action_verify_token()` — ручна перевірка, оновлює token_status
- `sync_from_meta(user_token)` — `@api.model`, масовий sync через `/me/accounts`
- `_check_single_default()` — constraint, скидає старий default

### 3.3 `sendpulse.message`

Окремі повідомлення розмови.

| Поле | Призначення |
|---|---|
| `connect_id` | М2О до `sendpulse.connect` |
| `direction` | Selection: `incoming` / `outgoing` |
| `text_message` | Текст |
| `attachment_url` | URL вкладення (якщо є) |
| `sp_message_id` | ID у SendPulse (для dedup) |
| `date` | Datetime |

### 3.4 `partner.sendpulse.message`

Архів переписки під `res.partner` (вкладка Messaging).

### 3.5 `partner.sendpulse.channel`

Соціальні канали партнера (Telegram/IG/FB link під полем VAT на картці).

### 3.6 `sendpulse.webhook.data`

Raw JSON аудит усіх вхідних webhook-ів. Очищається cron-ом через 7 днів.

| Поле | Призначення |
|---|---|
| `name` | Людиночитане ім'я контакту |
| `sendpulse_contact_id`, `service`, `event_type` | Metadata |
| `raw_data` | Повний JSON |
| `create_date` | Timestamp |

### 3.7 `sendpulse.identify.wizard`

TransientModel wizard для ручної ідентифікації `sendpulse.connect` з `res.partner`.

### 3.8 `res.config.settings` (inherit)

Всі Settings поля — ~270 рядків у `models/res_config_settings.py`. Поділ на секції:
- SendPulse OAuth
- Comment autoreply
- FB Page tokens + IG
- FB App credentials
- LLM classifier
- Telegram alerts
- Multi-page sync

Див. [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

### 3.9 `discuss.channel` (inherit)

Override у `models/mail_channel.py`:
- Додано `sendpulse_connect_id: Many2one('sendpulse.connect')`
- Override `message_post` для outbound flow через SendPulse API

---

## 4. Webhook flow

### 4.1 Endpoint

```
POST /sendpulse/webhook
Content-Type: application/json
X-SendPulse-Signature: <HMAC-SHA256>
```

**Controller:** `controllers/main.py`.

### 4.2 Обробка

```python
@http.route('/sendpulse/webhook', type='json', auth='public', csrf=False)
def sendpulse_webhook(self, **kwargs):
    # 1. Verify HMAC signature
    # 2. Store raw JSON у sendpulse.webhook.data
    # 3. Dispatch to sendpulse.connect._process_incoming_event
    return {'status': 'ok'}
```

### 4.3 JSON format від SendPulse

```json
{
  "title": "incoming_message",
  "service": "instagram",
  "bot": {"id": "...", "name": "..."},
  "contact": {
    "id": "69e...",
    "name": "Ольга Гладких",
    "email": "...",
    "phone": "...",
    "variables": {"child_name": "..."},
    "last_message": "Яка ціна",
    "last_message_data": {"message": {"type": "text"}}
  },
  "info": {
    "message": {
      "channel_data": {
        "message": {
          "text": "Яка ціна",
          "comment_id": "967504496232066_1480778583824126",
          "post_id": "...",
          "from": {"id": "...", "name": "..."},
          "page_id": "106771868966309"
        }
      }
    }
  }
}
```

### 4.4 Диспатч

У `_process_incoming_event`:

```python
is_comment = bool(
    channel_data_msg.get('comment_id') or
    (item == 'comment' and verb == 'add') or
    (media.media_product_type == 'FEED')
)
if is_comment:
    return self._process_comment_event(...)
return self._process_inbound(...)
```

### 4.5 Повний flow — див. §4 у [ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 5. SendPulse API інтеграція

### 5.1 OAuth

**Flow:** `client_credentials` grant → access_token з TTL 3600s.

```python
POST https://api.sendpulse.com/oauth/access_token
{
  "grant_type": "client_credentials",
  "client_id": "<client_id>",
  "client_secret": "<client_secret>"
}
→ {"access_token": "<access_token>", "expires_in": 3600}
```

**Cache:** `ir.config_parameter.oauth_access_token` + `oauth_valid_until`.
**Invalidation:** при 401 від будь-якого endpoint.
**Lock:** `pg_advisory_xact_lock(94219, 55817)` щоб один concurrent refresh.

### 5.2 Outbound messaging

```
POST https://api.sendpulse.com/{service}/contacts/send
Headers: Authorization: Bearer <access_token>
{
  "contact_id": "...",
  "text": "...",
  "attachment_url": "..."
}
```

### 5.3 Historical sync

```
GET https://api.sendpulse.com/chatbots/dialogs?bot_id=...&limit=100
```

Використовується у `cron_pull_missing_contacts` для відновлення після downtime.

---

## 6. Meta Graph API інтеграція

**Version:** `v25.0` (оновлений з v19.0 у v17.0.3.6.1). Центральний wrapper: `_fb_post_with_retry`.

### 6.1 Public reply під коментарем

**Facebook:**
```
POST /v25.0/{comment_id}/comments
{"message": "...", "access_token": "<page_token>"}
```

**Instagram:**
```
POST /v25.0/{comment_id}/replies
{"message": "...", "access_token": "<page_token>"}
```

### 6.2 Private reply

**Facebook:**
```
POST /v25.0/{comment_id}/private_replies
{"message": "...", "access_token": "<page_token>"}
```

**Instagram** (потребує `ig_business_id`):
```
POST /v25.0/{ig_user_id}/messages
{
  "recipient": {"comment_id": "<comment_id>"},
  "message": {"text": "..."},
  "access_token": "<page_token>"
}
```

**⚠️ Обмеження:** для коментарів під **FB Reels** Meta **не підтримує** `/private_replies` — повертає 100/33 `Unsupported post request`.

### 6.3 Hide comment

**Facebook:**
```
POST /v25.0/{comment_id}
{"is_hidden": true, "access_token": "<page_token>"}
```

**Instagram:**
```
POST /v25.0/{comment_id}
{"hide": true, "access_token": "<page_token>"}
```

### 6.4 Token health check

**Validity:**
```
GET /v25.0/me?fields=id,name&access_token=<token>
```

**Expiry (потребує app credentials):**
```
GET /v25.0/debug_token?input_token=<token>&access_token=<app_id>|<app_secret>
→ {"data": {"expires_at": <unix_ts>, "is_valid": true, "scopes": [...]}}
```

### 6.5 List Pages (для sync_from_meta)

```
GET /v25.0/me/accounts?fields=id,name,access_token,instagram_business_account,category&limit=50
```

**Важливо:** якщо `access_token` у запиті — **short-lived User Token**, то повернуті Page Tokens успадковують його expiry. Для безстрокових Page Tokens — спочатку exchange на long-lived User Token через `/oauth/access_token?grant_type=fb_exchange_token` (потребує `app_secret`).

### 6.6 Permissions (за App Review)

Див. §7.2 у [CONFIGURATION.md](docs/CONFIGURATION.md).

---

## 7. Anthropic LLM інтеграція

**Метод:** `sendpulse.connect._classify_comment(text, service)`.

### 7.1 Request

```python
POST https://api.anthropic.com/v1/messages
Headers:
  x-api-key: <anthropic_api_key>
  anthropic-version: 2023-06-01
  content-type: application/json
Body:
{
  "model": "claude-haiku-4-5",
  "max_tokens": 20,
  "messages": [{"role": "user", "content": "<prompt>"}]
}
```

### 7.2 Prompt structure (Ukrainian)

```
Класифікуй коментар під постом літнього дитячого табору CampScout
в одну з категорій:
- question_price
- question_dates
- question_age
- question_general
- thanks
- complaint
- spam
- other

Коментар: "<first 400 chars>"

Відповідай ОДНИМ СЛОВОМ — назвою категорії без пояснень.
```

### 7.3 Response parsing

```python
raw = response['content'][0]['text'].strip().lower()
for category in _COMMENT_CATEGORIES:
    if category in raw:
        return category
return 'other'  # unknown response
```

### 7.4 Cost estimate

**Model:** Claude Haiku 4.5.
**Input:** ~200 tokens / comment.
**Output:** ~8 tokens / comment.
**Cost:** ~$0.20 / 1000 comments.

---

## 8. Telegram Bot API інтеграція

**Метод:** `sendpulse.connect._notify_telegram(text, silent=False)`.

### 8.1 Request

```python
POST https://api.telegram.org/bot<bot_token>/sendMessage
{
  "chat_id": "<chat_id>",
  "text": "<HTML text, ≤ 4000 chars>",
  "parse_mode": "HTML",
  "disable_notification": <silent>,
  "disable_web_page_preview": true
}
```

### 8.2 Події

| Подія | Тип | Триггер |
|---|---|---|
| 🚨 СКАРГА під постом | loud | LLM category=`complaint` у `_process_comment_event` |
| 🚫 Спам приховано | silent | `_hide_comment` ok після LLM `spam` |
| ⏳ 24h вікно закривається | silent | `cron_check_messenger_windows` |
| ⚠️ FB Token недійсний / ≤7д | loud | `_check_single_fb_token` |

### 8.3 Fallback

Якщо `telegram_alerts_enabled=False` або токен порожній — `_notify_telegram` повертає `False` без помилок, flow продовжується.

---

## 9. Discuss інтеграція

### 9.1 discuss.channel лінк

Кожен `sendpulse.connect` має `channel_id` Many2one до `discuss.channel` (1:1). Channel має reverse link `sendpulse_connect_id`.

### 9.2 Operator pickup flow

```python
def action_open_discuss(self):
    # 1. Create channel if needed
    if not self.channel_id:
        self._create_discuss_channel()
    # 2. Add current user як member якщо ще ні
    if not member_exists:
        self.channel_id.add_members(partner_ids=[env.user.partner_id.id])
    # 3. Skip new_message indicator
    if self.stage == 'new_message':
        self.write({'stage': 'in_progress'})
    # 4. Open Discuss action
    return {'type': 'ir.actions.client', 'tag': 'mail.action_discuss', ...}
```

### 9.3 Outbound message override (`models/mail_channel.py`)

```python
def message_post(self, **kwargs):
    result = super().message_post(**kwargs)
    # Skip якщо це system message (context.sendpulse_incoming=True)
    if self.env.context.get('sendpulse_incoming'):
        return result
    # Otherwise — send to SendPulse API
    connect = self.sendpulse_connect_id
    if connect and not connect.sp_is_comment:
        connect.send_message_to_sendpulse(
            text=extract_text(kwargs['body']),
            attachment_url=extract_attachment(kwargs.get('attachment_ids')),
        )
    return result
```

---

## 10. Cron tasks

Див. [CONFIGURATION.md §4](docs/CONFIGURATION.md#4-cron-schedule) для повного reference.

**Короткий огляд:**

| Cron | Interval | Модель.метод |
|---|---|---|
| Webhook data cleanup | 1d | `sendpulse.webhook.data.cron_clean` |
| Discuss channel sync | 1h | `sendpulse.connect.cron_sync_discuss_channels` |
| Missing contacts recovery | 6h | `sendpulse.connect.cron_pull_missing_contacts` |
| FB Token expiry check | 7d | `sendpulse.connect.cron_check_fb_token_expiry` |
| Messenger 24h window warning | 30m | `sendpulse.connect.cron_check_messenger_windows` |

---

## 11. Security & ACL

### 11.1 Групи

**Файл:** `security/security.xml`.

- `group_sendpulse_officer` — бачить свої розмови
- `group_sendpulse_admin` — повний доступ + Pages + Settings

### 11.2 Record rules

```xml
<!-- Officer: тільки свої -->
<record id="sendpulse_connect_rule_officer" model="ir.rule">
    <field name="name">SendPulse Connect — Officer own</field>
    <field name="model_id" ref="model_sendpulse_connect"/>
    <field name="domain_force">[('user_id', '=', user.id)]</field>
    <field name="groups" eval="[(4, ref('group_sendpulse_officer'))]"/>
</record>
```

### 11.3 ACL (`security/ir.model.access.csv`)

| Model | Officer | Admin |
|---|---|---|
| `sendpulse.connect` | read/write | CRUD |
| `sendpulse.message` | CRUD | CRUD |
| `sendpulse.webhook.data` | unlink only | CRUD |
| `partner.sendpulse.message` | CRUD | CRUD |
| `partner.sendpulse.channel` | CRUD | CRUD |
| `sendpulse.identify.wizard` | CRUD | CRUD |
| `sendpulse.facebook.page` | read-only | CRUD |

### 11.4 Secrets

Всі секретні поля зберігаються у `ir.config_parameter`:
- `sendpulse_client_secret`
- `fb_page_access_token`
- `fb_app_secret`
- `anthropic_api_key`
- `telegram_bot_token`

У view — атрибут `password="True"` (приховує значення і при reopen треба перевводити).

У audit log `access_token` у payload завжди замінюється на `***REDACTED***`.

---

## 12. Migration notes

### 12.1 З v17.0.3.6.x → 17.0.3.7.x

**Breaking:** нема.

**Auto-migrations:**
- Додано поле `sp_page_id` на `sendpulse.connect` — заповнюється автоматично у `_process_comment_event` при нових webhooks. Існуючі записи мають `null` — це OK, вони використовують fallback на default Page або legacy token.
- Нова модель `sendpulse.facebook.page` — таблиця порожня при першому запуску, sync через Settings UI.

**Cleanup:**
- Deprecated ICP keys (`ai_*`) можна видалити вручну (безпечно).
- Legacy `fb_page_access_token` продовжує працювати як fallback.

### 12.2 Race condition cleanup (2026-04-20)

14 пар дублів `sendpulse.connect` merged через одноразовий shell скрипт. Запис в LOG.md, cleanup код не у production модулі.

### 12.3 Graph API v19 → v25 (2026-04-19)

Всі URL оновлено. v19 deprecated Meta у 2026. Немає breaking changes у response format для використовуваних endpoints.

---

## 13. Testing

### 13.1 Запуск unit tests

```bash
docker exec campscout_web /usr/bin/odoo \
    -d test_db \
    --test-enable --stop-after-init \
    -i odoo_chatwoot_connector \
    --log-level=test
```

### 13.2 Smoke test на production

Див. §8.6 у [CONFIGURATION.md](docs/CONFIGURATION.md).

### 13.3 Manual integration test

1. У SendPulse webhook settings → Test webhook → перевірити що прийшов `sendpulse.webhook.data` запис
2. Написати з особистого IG на FB-сторінку → перевірити що створилося `sendpulse.connect` з `stage=new`
3. Відкрити запис → натиснути «Відкрити чат» → перевірити що Discuss-канал відкрився
4. Написати у Discuss → перевірити що повідомлення прийшло у IG-месенджер

### 13.4 LLM classifier test

```python
# odoo shell
Connect = env['sendpulse.connect'].sudo()
for text, expected in [
    ('Яка ціна табору?', 'question_price'),
    ('Дякую!', 'thanks'),
    ('Це лохотрон', 'complaint'),
    ('🔥 crypto pump', 'spam'),
]:
    result = Connect._classify_comment(text, 'facebook')
    assert result == expected, f'{text} → {result}, expected {expected}'
```

### 13.5 Telegram alert test

```python
# odoo shell
env['sendpulse.connect'].sudo()._notify_telegram(
    '✅ Test alert from v17.0.3.7.1', silent=False
)
# → True якщо бот у групі, інакше False
```

---

## Додатки

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — детальна архітектура + flows + ER
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — усі налаштування
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — install / upgrade / rollback
- [docs/TZ.md](docs/TZ.md) — umbrella TZ
- [docs/TZ_COMMENT_AUTOREPLY.md](docs/TZ_COMMENT_AUTOREPLY.md) — sub-TZ на comment autoreply
- [CHANGELOG.md](CHANGELOG.md) — релізний журнал

---

*Documentation standard: Markdown GFM-style. Усі приклади коду — на Python 3.10+ / Odoo 17 idioms. Усі URL чинні на 2026-04-20. Оновлюється при кожному major/minor release.*
