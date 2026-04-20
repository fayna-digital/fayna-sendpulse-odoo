# Architecture — Fayna SendPulse Odo

**Module version:** `17.0.3.7.1` · **Last updated:** 2026-04-20

---

## Зміст

1. [Огляд системи](#1-огляд-системи)
2. [Компоненти](#2-компоненти)
3. [Модель даних](#3-модель-даних)
4. [Flows — крок-за-кроком](#4-flows--крок-за-кроком)
5. [Механіки надійності](#5-механіки-надійності)
6. [Інтеграції](#6-інтеграції)
7. [Cron tasks](#7-cron-tasks)
8. [Security model](#8-security-model)
9. [Розширення і точки інжекції](#9-розширення-і-точки-інжекції)

---

## 1. Огляд системи

Модуль — **bridge** між **SendPulse chatbots** (Telegram / IG / FB / Messenger / WhatsApp / Viber / LiveChat / TikTok) та **Odoo Discuss** з окремою гілкою для **автоматичних відповідей на коментарі FB / Instagram** через Meta Graph API.

Дві паралельні поведінки під одним dataflow:

```
                        SendPulse webhook event
                                   │
                                   ▼
             ┌─────── is_comment? ──┴──┐
             │                          │
           false                       true
             │                          │
             ▼                          ▼
     ┌───────────────┐         ┌────────────────────┐
     │ Direct chat   │         │ Comment under post │
     │ flow          │         │ flow               │
     └───────┬───────┘         └─────────┬──────────┘
             │                           │
             ▼                           ▼
      sendpulse.connect            sendpulse.connect
      (sp_is_comment=false)        (sp_is_comment=true)
             │                           │
             ▼                           ▼
      discuss.channel              discuss.channel
      ([TG]/[IG]/[FB]…)            ([MSG]/[IG]…)
             │                           │
             ▼                           │
      operator picks up                  │
      from queue                         ├─ Meta Graph API
             │                           │  ├─ public reply
             ▼                           │  ├─ private reply
      mail.message →                     │  └─ hide_comment
      SendPulse REST API                 │
             │                           ▼
             ▼                  Audit log + Telegram alerts
       клієнт у месенджері
```

## 2. Компоненти

### 2.1 Controller (`controllers/main.py`)

```
POST /sendpulse/webhook
 ├── HMAC/Bearer token verification (sendpulse_webhook_token)
 ├── SSRF guard для inline media URLs
 ├── raw JSON → sendpulse.webhook.data (audit trail)
 └── sendpulse.connect._process_incoming_event(data, contact, bot, service, event_type, timestamp_ms)
```

Webhook responds **200 OK** швидко — важка робота через env. У critical path тільки вхідна валідація і create raw record.

### 2.2 Central model (`models/sendpulse_connect.py`, 2600+ рядків)

Монолітна модель з двома основними entry point методами:

- `_process_incoming_event(data, contact, bot, service, event_type, ts)` — диспатчер:
  - Якщо `is_comment(channel_data_msg)` — делегує у `_process_comment_event`
  - Інакше — `_process_inbound` (DM flow)

- `_process_comment_event(...)` — повний flow коментаря (див. §4.2)

### 2.3 Multi-page model (`models/sendpulse_facebook_page.py`)

Окрема модель що тримає всі Facebook Pages з їхніми Page Access Tokens.

```python
_name = 'sendpulse.facebook.page'

name: Char
page_id: Char (unique, indexed)     # FB Page ID
access_token: Char                  # безстроковий Page Token
ig_business_id: Char                # linked IG Business Account ID
category: Char                      # з /me/accounts
active: Boolean
is_default: Boolean                 # fallback для webhook-ів без page_id
last_checked_at: Datetime
token_status: Char                  # valid / invalid / expires_soon: Nd
landing_url, tg_url, yt_url: Char   # per-page URL overrides
```

Ключові методи:
- `find_by_page_id(page_id)` — лукап з fallback на default
- `action_verify_token()` — ручна перевірка через `GET /v25.0/{page_id}`
- `sync_from_meta(user_token)` — створює/оновлює записи через `/me/accounts`

### 2.4 Overrides

- `models/mail_channel.py` — `discuss.channel._inherit`: override `message_post` щоб вихідні повідомлення оператора летіли через SendPulse REST API
- `models/res_partner.py` — розширення картки партнера (вкладка Messaging, список каналів)
- `models/res_config_settings.py` — TransientModel з усіма Settings полями

### 2.5 Frontend (OWL)

- `static/src/thread_patch.js` — патч `Thread` моделі з `sendpulseConnectId`
- `static/src/components/sendpulse_info_panel/*` — OWL компонент бокової панелі
- `static/src/sendpulse_thread_actions.js` — реєстрація дії у `threadActionsRegistry`

---

## 3. Модель даних

### 3.1 ER-діаграма

```
┌──────────────────┐  1:1   ┌──────────────────┐
│  res.partner     │────────│ partner.sendpulse│
│                  │   ∞:1  │ .channel         │──┐
└────────┬─────────┘        └──────────────────┘  │
         │                                         │
         │ ∞:1                                     │
         │                                         │
         ▼                                         │
┌──────────────────────┐   1:∞   ┌────────────┐   │
│  sendpulse.connect   │─────────│ sendpulse  │   │
│                      │         │ .message   │   │
│  (розмова)           │         └────────────┘   │
│                      │                           │
│  ├─ sp_page_id ─────▶ sendpulse.facebook.page ──┘
│  ├─ partner_id ─────▶ res.partner
│  ├─ channel_id ─────▶ discuss.channel (1:1)
│  ├─ sp_lead_id ─────▶ crm.lead
│  └─ source_id ──────▶ utm.source
│
│  [коментарні поля]
│  ├─ sp_is_comment, sp_comment_id, sp_comment_text
│  ├─ sp_post_id, sp_post_url
│  ├─ sp_replied_public, sp_replied_private
│  ├─ sp_comment_category (Selection, 8 values)
│  │
│  [24h window tracking]
│  ├─ sp_messenger_window_expires_at
│  └─ sp_window_alert_sent
│
│  [funnel metrics]
│  ├─ sp_funnel_stage (Selection, 7 stages)
│  ├─ sp_first_inbound_at, sp_first_reply_at
│  └─ sp_first_reply_time_sec (computed, stored)
└──────────────────────┘

┌────────────────────────┐
│ sendpulse.webhook.data │  — raw JSON audit (7-day TTL через cron)
└────────────────────────┘

┌──────────────────────────┐
│ partner.sendpulse.message │  — архів переписки на картці партнера
└──────────────────────────┘
```

### 3.2 `sendpulse.connect` — центральна модель

| Group | Поля |
|---|---|
| Ідентифікація | `name`, `sendpulse_contact_id`, `service`, `stage`, `bot_id`, `bot_name`, `partner_id`, `social_username`, `social_profile_url` |
| Unidentified | `unidentified_email`, `unidentified_phone`, `is_unidentified` (computed) |
| Bot variables | `sp_child_name`, `sp_booking_email`, `avatar_url`, `language_code`, `subscription_status` |
| Discuss | `channel_id`, `message_ids`, `message_count`, `last_notified_at` |
| UTM | `source_id` |
| **Comments** | `sp_is_comment`, `sp_comment_id`, `sp_comment_text`, `sp_post_id`, `sp_post_url`, `sp_page_id`, `sp_replied_public`, `sp_replied_private`, `sp_comment_category` |
| **24h window** | `sp_messenger_window_expires_at`, `sp_window_alert_sent` |
| **Funnel** | `sp_funnel_stage`, `sp_first_inbound_at`, `sp_first_reply_at`, `sp_first_reply_time_sec`, `sp_lead_id` |

### 3.3 Stage machine

```
         ┌─────────┐
         │  new    │  unidentified contact — чекає ідентифікації у черзі
         └────┬────┘
              │  identify_wizard / auto-match
              ▼
         ┌─────────────┐
         │ in_progress │  оператор взяв у роботу
         └──────┬──────┘
                │  inbound від клієнта
                ▼
         ┌──────────────────┐
         │  new_message     │  потребує відповіді
         └──────┬───────────┘
                │  operator reply
                ▼
         ┌─────────────┐
         │ in_progress │
         └──────┬──────┘
                │  action_close()
                ▼
         ┌─────────┐
         │  close  │
         └─────────┘
```

### 3.4 Funnel stages (`sp_funnel_stage`)

```
comment_only ──▶ private_sent ──▶ customer_replied ──▶ operator_engaged
                                                            │
                                                            ▼
                                                      lead_created
                                                            │
                                                            ▼
                                                ┌── closed_won
                                                │
                                                └── closed_lost
```

---

## 4. Flows — крок-за-кроком

### 4.1 Direct chat (DM) flow

```
1. POST /sendpulse/webhook (Telegram / IG / WA / etc.)
      │
2. controllers/main.py
   ├── verify webhook token (HMAC)
   ├── SSRF-check media URLs (if any)
   ├── INSERT INTO sendpulse.webhook.data (raw JSON)
   └── call sendpulse.connect._process_incoming_event(...)
      │
3. _process_incoming_event → not comment → _process_inbound
   │
4. _process_inbound:
   │
   ├── extract: contact_id, name, email, phone, message_type, variables
   ├── parse social_username, photo_url, bot variables (child_name, booking_email)
   │
   ├── [Step 1] _find_partner(contact_id, email, phone, variables)
   │            ├── search res.partner by bot variables (priority 1)
   │            ├── search by email (priority 2)
   │            └── search by phone (priority 3)
   │
   ├── [Race-guard] pg_advisory_xact_lock(hash(contact_id|service), KEY)
   │               (v17.0.3.7.1 fix — два concurrent webhook-и чекають по черзі)
   │
   ├── [Step 2] find-or-create sendpulse.connect:
   │            ├── by sendpulse_contact_id + service (active)
   │            ├── by partner_id + service (якщо партнер визначений)
   │            └── reopen closed
   │
   ├── update fields, fill 24h window, first_inbound_at, funnel_stage=customer_replied
   │
   ├── if new → send auto-greeting (два налаштовуваних повідомлення через SendPulse)
   │
   ├── attach mail.message до discuss.channel (якщо exists)
   │
   └── post notification to operators (черга стадія `new_message` / `new`)
      │
5. Queue-based pickup:
   ├── оператор бачить запис у SendPulse list view
   ├── клікає → action_open_discuss
   │          ├── adds self як channel_member
   │          ├── stage: new_message → in_progress
   │          └── opens mail.action_discuss
   │
6. Operator types response у Discuss (mail_channel.message_post):
   ├── [Override] models/mail_channel.py
   ├── if operator (not 'sendpulse_incoming' context):
   │   └── send via SendPulse REST API → {attempts=3, backoff}
   └── partner.sendpulse.message archived under res.partner
      │
7. Client receives message in messenger ✓
```

### 4.2 Comment under post flow (FB Reel / Post / IG Feed)

```
1. SendPulse webhook delivers incoming_message WITH channel_data.comment_id
   (FB format: item='comment', verb='add' OR IG format: media.media_product_type='FEED')
      │
2. Controller → _process_incoming_event → is_comment=True → _process_comment_event
      │
3. _process_comment_event:
   │
   ├── parse comment_id, comment_text, post_id, post_url
   ├── read ICP.sp_comment_autoreply_enabled — якщо False, return None
   │
   ├── [Multi-page] Page = sendpulse.facebook.page.find_by_page_id(page_id_from_payload)
   │                ├── match by page_id
   │                └── fallback: is_default=True
   │
   ├── [Self-loop guard] collect own_ids from всіх active pages + legacy ig_user_id
   │                     if from.id in own_ids → skip (не відповідаємо на свій коментар)
   │
   ├── [Race-guard] pg_advisory_xact_lock(hash('comment|'+comment_id), KEY)
   │
   ├── [Dedup] search by sp_comment_id — if exists → return existing
   │
   ├── find-or-create sendpulse.connect з sp_is_comment=True, sp_page_id, sp_funnel_stage='comment_only'
   │
   ├── _create_discuss_channel() — [MSG]/[IG] {name} (0 members за замовчуванням)
   │
   ├── [LLM] _classify_comment(text, service) → category ∈ {
   │         question_price, question_dates, question_age, question_general,
   │         thanks, complaint, spam, other
   │       }
   │   ├── if llm_classifier_enabled=False або no api_key → 'other'
   │   ├── POST https://api.anthropic.com/v1/messages (Claude Haiku, ~50ms)
   │   └── parse response → one of 8 categories
   │
   ├── [Routing]
   │   ├── thanks → send_public=False, send_private=False (не відповідаємо на "дякую")
   │   ├── spam   → send_public=False, send_private=False
   │   │           + if sp_comment_hide_spam_enabled: _hide_comment(comment_id, service, page=page)
   │   │           + Telegram silent alert
   │   ├── complaint → send_public=False, send_private=False
   │   │           + Telegram 🚨 alert з текстом і лінком на пост
   │   └── question_* / other → normal flow
   │
   ├── [Dedup check] already_private = search by contact_id + sp_replied_private=True
   │                 has_direct_dialog = search by contact_id + sp_is_comment=False
   │                 send_private = not already_private AND not has_direct_dialog
   │
   ├── [Public reply]
   │   ├── count = search_count by (sp_post_id, sp_replied_public=True)  ← per-post rotation
   │   ├── text = _COMMENT_PUBLIC_TEMPLATES[count % 5] або REPEAT_TEMPLATE якщо вже був private
   │   ├── _send_comment_public_reply(comment_id, service, text, page=page)
   │   │   ├── POST /v25.0/{comment_id}/comments    (FB)
   │   │   └── POST /v25.0/{comment_id}/replies     (IG)
   │   │   via _fb_post_with_retry(retries=3, backoff=1s/3s/9s)
   │   └── if ok → connect.write({'sp_replied_public': True})
   │
   ├── [Private reply] (якщо send_private=True)
   │   ├── text = ICP.sp_comment_private_text або дефолт з {landing_url, tg_url, yt_url}
   │   ├── _send_comment_private_reply(comment_id, text, service, page=page)
   │   │   ├── FB:  POST /v25.0/{comment_id}/private_replies
   │   │   └── IG:  POST /v25.0/{ig_user_id}/messages з recipient.comment_id
   │   │       (ig_user_id з page.ig_business_id або legacy config)
   │   └── if ok → connect.write({
   │       'sp_replied_private': True,
   │       'sp_messenger_window_expires_at': now + 24h,
   │       'sp_funnel_stage': 'private_sent',
   │     })
   │
   └── _notify_operator_comment(...) — нотатка у Discuss-каналі
```

### 4.3 Operator reply flow

```
Operator types message in Odoo Discuss
     │
     ▼
discuss.channel.message_post(body, ...)
     │  [override у mail_channel.py]
     ▼
if not context.sendpulse_incoming:
   ├── extract text + attachments
   ├── send_message_to_sendpulse(text, attachment_url)
   │   ├── POST SendPulse API /chatbots/messages
   │   └── writes partner.sendpulse.message для архіву
   │
   └── on success:
       ├── if first reply: sp_first_reply_at, funnel='operator_engaged'
       ├── stage: new_message → in_progress
       └── sp_messenger_window_expires_at = now + 24h
```

---

## 5. Механіки надійності

### 5.1 `_fb_post_with_retry(url, payload, label, attempts=3, base_delay=1)`

Exponential backoff wrapper для всіх Graph API викликів.

```python
for attempt in range(attempts):
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            _log_fb_audit(...)  # INFO
            return True, None, resp.json()
        if resp.status_code in (429, 500..599):
            # retry
            _logger.warning('... retrying')
        else:
            # 4xx (не 429) — permanent error, no retry
            _log_fb_audit(...)  # WARNING
            return False, err, None
    except (ConnectionError, Timeout):
        # network error — retry
        pass
    time.sleep(base_delay * (3 ** attempt))  # 1s, 3s, 9s
_log_fb_audit(...)  # ERROR
return False, 'retries exhausted', None
```

### 5.2 Audit log (`_log_fb_audit`)

Кожен виклик (success / 4xx no-retry / exhausted / exception) пише у `ir.logging`:

```
level: INFO | WARNING | ERROR
name:  odoo_chatwoot_connector.fb_api
path:  sendpulse_connect._fb_post_with_retry
func:  <label: e.g. "public-reply 12345_67890">
message:
  [label] <status> attempts=N
  URL: <full url>
  Payload: {..., 'access_token': '***REDACTED***'}
  Response: <first 500 chars>
```

Пошук: **Technical → Logging → filter name=odoo_chatwoot_connector.fb_api**.

### 5.3 PostgreSQL advisory lock

Two places:

```python
# _process_inbound (для DMs)
lock_key = md5(f'{contact_id}|{service}')[:8] as int
cr.execute('SELECT pg_advisory_xact_lock(%s, %s)', (lock_key, KEY))

# _process_comment_event (для коментарів)
lock_key = md5(f'comment|{comment_id}')[:8] as int
cr.execute('SELECT pg_advisory_xact_lock(%s, %s)', (lock_key, KEY))
```

Lock автоматично звільняється при commit/rollback транзакції. Без нього — race condition при одночасних webhook-ах (виявили 14 пар дублів на проді 2026-04-20).

### 5.4 Idempotency

- Comment дедуп: `search([('sp_comment_id', '=', comment_id)])` перед create
- Webhook дедуп: `sendpulse.webhook.data` тримає raw JSON — повторний webhook з тим же `event_id` ігнорується
- Message дедуп: `sendpulse_incoming=True` context запобігає re-sending у SendPulse при системних message_post

### 5.5 Self-loop guard

У `_process_comment_event`:

```python
own_ids = {page_id_from_payload, legacy_ig_user_id}
for p in sendpulse.facebook.page.search([('active','=',True)]):
    own_ids.add(p.page_id)
    own_ids.add(p.ig_business_id)

if from_id in own_ids:
    skip  # це наша публічна відповідь, не клієнта
```

Без цього — infinite loop: наша публічна відповідь приходить як webhook → ми на неї знов відповідаємо.

---

## 6. Інтеграції

### 6.1 Meta Graph API (v25.0)

| Endpoint | Метод | Використання |
|---|---|---|
| `/v25.0/{comment_id}/comments` | POST | Public reply FB |
| `/v25.0/{comment_id}/replies` | POST | Public reply IG |
| `/v25.0/{comment_id}/private_replies` | POST | Private reply FB |
| `/v25.0/{ig_user_id}/messages` | POST | Private reply IG (recipient.comment_id) |
| `/v25.0/{comment_id}` | POST (is_hidden:true) | Hide spam FB |
| `/v25.0/{comment_id}` | POST (hide:true) | Hide spam IG |
| `/v25.0/me` | GET | Health check token |
| `/v25.0/me/accounts` | GET | List pages (для sync_from_meta) |
| `/v25.0/debug_token` | GET | Token expiry info (потребує app_id+secret) |

### 6.2 SendPulse REST API

- OAuth 2.0 з app cache у `ir.config_parameter` (TTL 3600s)
- `POST /oauth/access_token` — invalidated при 401
- Outbound messaging: `POST /chatbots/messages` / `POST /telegram/contacts/send` etc.
- Historical sync: `GET /chatbots/dialogs` (через `cron_pull_missing_contacts`)

### 6.3 Anthropic API

- `POST https://api.anthropic.com/v1/messages`
- Headers: `x-api-key`, `anthropic-version: 2023-06-01`
- Model: `claude-haiku-4-5` (за замовчуванням, configurable)
- Prompt: структурований для 8-категорної класифікації
- Timeout: 10 секунд
- Фолбек `'other'` на будь-яку помилку

### 6.4 Telegram Bot API

- `POST https://api.telegram.org/bot{token}/sendMessage`
- `parse_mode: HTML`, `disable_notification` для silent
- Текст ≤ 4000 символів (обрізається)
- Фолбек `False` на HTTP != 200 — не ламає основний flow

---

## 7. Cron tasks

Визначені в `data/clean_data_cron.xml`:

| Назва | Модель.метод | Interval | Призначення |
|---|---|---|---|
| SendPulse Odo: Очищення webhook даних | `sendpulse.webhook.data.cron_clean` | 1 day | Видалити `sendpulse.webhook.data` старше 7 днів |
| SendPulse Odo: Авто-синхронізація Discuss каналів | `sendpulse.connect.cron_sync_discuss_channels` | 1 hour | Створити discuss.channel для розмов які не мають каналу |
| SendPulse Odo: Повернення втрачених контактів | `sendpulse.connect.cron_pull_missing_contacts` | 6 hours | Через SendPulse REST витягує всі діалоги за останні 24h — відновлює пропущені webhooks |
| **SendPulse Odo: Перевірка FB Page Access Token** | `sendpulse.connect.cron_check_fb_token_expiry` | 7 days | Усі active sendpulse.facebook.page + legacy — `GET /me` + `/debug_token`, пише `token_status` |
| **SendPulse Odo: Попередження про закриття 24h вікна** | `sendpulse.connect.cron_check_messenger_windows` | 30 min | Шукає розмови де `sp_messenger_window_expires_at` менше 2h → Telegram alert + нотатка |

---

## 8. Security model

### 8.1 Групи

- `group_sendpulse_officer` — веде свої чати (`user_ids` filter)
- `group_sendpulse_admin` — повний доступ + керує Pages + Settings

### 8.2 Record rules

- Officer бачить `sendpulse.connect` WHERE `user_id == current_user`
- Admin — без обмеження
- `sendpulse.facebook.page` — тільки admin має write/create/unlink

### 8.3 ACL (`ir.model.access.csv`)

| Модель | Officer | Admin |
|---|---|---|
| `sendpulse.connect` | r/w | CRUD |
| `sendpulse.message` | CRUD | CRUD |
| `sendpulse.webhook.data` | unlink only | CRUD |
| `partner.sendpulse.message` | CRUD | CRUD |
| `partner.sendpulse.channel` | CRUD | CRUD |
| `sendpulse.identify.wizard` | CRUD | CRUD |
| `sendpulse.facebook.page` | read-only | CRUD |

### 8.4 Secrets management

- `sendpulse_client_secret` / `fb_page_access_token` / `anthropic_api_key` / `telegram_bot_token` / `fb_app_secret` зберігаються у `ir.config_parameter` з `password="True"` у view
- У audit log `access_token` завжди `***REDACTED***`
- Webhook verification через `sendpulse_webhook_token` (HMAC або Bearer)

---

## 9. Розширення і точки інжекції

### 9.1 Додати підтримку нового месенджера

1. Розширити `SERVICE_SELECTION` у `sendpulse_connect.py`
2. Додати іконку у `_compute_service_icon`
3. Додати в список у `_get_service_label`
4. (Опціонально) додати UTM source у `data/sendpulse_utm_data.xml`

### 9.2 Додати нову категорію класифікатора

1. Розширити `_COMMENT_CATEGORIES` tuple у `sendpulse_connect.py`
2. Додати label в `_CATEGORY_LABELS`
3. Додати обробку у routing в `_process_comment_event`
4. Оновити prompt у `_classify_comment`

### 9.3 Додати нову cron-задачу

1. Написати `@api.model cron_xxx(self)` у `sendpulse_connect.py` (або окремо)
2. Додати `<record id="ir_cron_xxx" model="ir.cron">` у `data/clean_data_cron.xml`
3. Upgrade модуля щоб cron зареєструвався

### 9.4 Додати новий Telegram алерт

Викликати `self._notify_telegram(text, silent=False)` з будь-якого методу. HTML-тегами: `<b>`, `<i>`, `<code>`, emoji unicode.

---

*Документ згенерований для v17.0.3.7.1. Оновлюється при додаванні нових flow/моделей/механік.*
