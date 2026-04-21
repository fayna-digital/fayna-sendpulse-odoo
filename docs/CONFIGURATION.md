# Configuration — Fayna SendPulse Odoo

**Module version:** `17.0.3.7.1` · **Last updated:** 2026-04-20

Довідник усіх налаштувань: поля у Settings UI, ключі у `ir.config_parameter`, cron-задачі, права користувачів.

---

## Зміст

1. [Settings UI (Налаштування → SendPulse Odoo)](#1-settings-ui)
2. [Config parameters reference](#2-config-parameters-reference)
3. [Facebook Pages (multi-page)](#3-facebook-pages-multi-page)
4. [Cron schedule](#4-cron-schedule)
5. [Groups & permissions](#5-groups--permissions)
6. [Webhook setup у SendPulse](#6-webhook-setup-у-sendpulse)
7. [Meta App setup](#7-meta-app-setup)
8. [Receipts / checklist](#8-receipts--checklist)

---

## 1. Settings UI

**Шлях:** Odoo → Settings → Apps → SendPulse Odoo → кнопка «Налаштування».
Або через top menu: SendPulse → Налаштування.

### 1.1 SendPulse API

| Поле | ICP ключ | Приклад | Обов'язкове |
|---|---|---|---|
| SendPulse Client ID | `odoo_chatwoot_connector.client_id` | `abc123...` | ✅ |
| SendPulse Client Secret | `odoo_chatwoot_connector.client_secret` | `xyz...` | ✅ |
| Webhook Secret Token | `odoo_chatwoot_connector.webhook_token` | `sp_whk_2026...` | ✅ |
| Webhook URL (readonly) | — | `https://YOUR/sendpulse/webhook` | — |

### 1.2 Відповіді на коментарі FB / Instagram

| Поле | ICP ключ | Default |
|---|---|---|
| Автовідповідь на коментарі FB/IG | `odoo_chatwoot_connector.sp_comment_autoreply_enabled` | `True` |
| Публічна відповідь під коментарем | `odoo_chatwoot_connector.sp_comment_public_enabled` | `True` |
| Приватне повідомлення (перший коментар) | `odoo_chatwoot_connector.sp_comment_private_enabled` | `True` |
| Facebook Page Access Token (legacy) | `odoo_chatwoot_connector.fb_page_access_token` | — |

**Note:** `fb_page_access_token` — legacy fallback. Після налаштування `sendpulse.facebook.page` записів модуль автоматично використовує per-page токени; цей використовується якщо Page не резолвиться.

### 1.3 Instagram

| Поле | ICP ключ | Приклад |
|---|---|---|
| Instagram Business Account ID | `odoo_chatwoot_connector.ig_user_id` | `17841457668400063` |

Legacy fallback. При multi-page — береться з `sendpulse.facebook.page.ig_business_id`.

### 1.4 Facebook App (для `/debug_token`)

| Поле | ICP ключ | Джерело |
|---|---|---|
| Facebook App ID | `odoo_chatwoot_connector.fb_app_id` | developers.facebook.com → App → Basic Settings |
| Facebook App Secret | `odoo_chatwoot_connector.fb_app_secret` | там же (Show) |
| Статус Page Token | `odoo_chatwoot_connector.fb_token_status` (readonly) | оновлюється cron-ом |
| Остання перевірка | `odoo_chatwoot_connector.fb_token_last_check` (readonly) | оновлюється cron-ом |

Без App credentials cron каже `valid (no app_id/secret for expiry)` — без точного `days_left`.

### 1.5 Шаблони відповідей

| Поле | ICP ключ | Використання |
|---|---|---|
| Landing URL | `odoo_chatwoot_connector.sp_comment_landing_url` | `{landing_url}` у шаблонах публічних |
| Telegram URL | `odoo_chatwoot_connector.sp_comment_tg_url` | `{tg_url}` у шаблонах |
| YouTube URL | `odoo_chatwoot_connector.sp_comment_yt_url` | `{yt_url}` у приватному повідомленні |
| Текст приватного повідомлення | `odoo_chatwoot_connector.sp_comment_private_text` | Override дефолту; підтримує `{landing_url}`, `{tg_url}`, `{yt_url}` |

**Per-page override** (пріоритет): `sendpulse.facebook.page.landing_url / tg_url / yt_url`. Якщо null → fallback на глобальний ICP.

### 1.6 Multi-page Facebook/Instagram

| Поле | Тип | Призначення |
|---|---|---|
| Зареєстрованих Pages | `fb_pages_count` (computed) | Показує кількість активних записів |
| User Access Token (тимчасово) | `fb_sync_user_token` (не зберігається) | Для `sync_from_meta` |
| Кнопка «Синхронізувати з Meta /me/accounts» | — | Викликає `action_sync_fb_pages()` |

### 1.7 LLM-класифікатор коментарів

| Поле | ICP ключ | Default |
|---|---|---|
| LLM-класифікатор коментарів (toggle) | `odoo_chatwoot_connector.llm_classifier_enabled` | `False` |
| Anthropic API Key | `odoo_chatwoot_connector.anthropic_api_key` | — |
| LLM Model | `odoo_chatwoot_connector.llm_model` | `claude-haiku-4-5` |
| Автоматично приховувати спам | `odoo_chatwoot_connector.sp_comment_hide_spam_enabled` | `True` |

### 1.8 Telegram-алерти менеджерам

| Поле | ICP ключ | Default |
|---|---|---|
| Telegram-алерти менеджерам (toggle) | `odoo_chatwoot_connector.telegram_alerts_enabled` | `False` |
| Telegram Bot Token | `odoo_chatwoot_connector.telegram_bot_token` | — |
| Telegram Chat ID | `odoo_chatwoot_connector.telegram_chat_id` | — |

---

## 2. Config parameters reference

Всі ключі мають префікс `odoo_chatwoot_connector.` (історичний).

### 2.1 Системні / OAuth

```
client_id                    — SendPulse OAuth Client ID
client_secret                — SendPulse OAuth Client Secret
webhook_token                — токен перевірки вхідних webhook-ів
oauth_access_token           — кеш SendPulse access_token (з TTL)
oauth_valid_until            — експірація кешу у Unix timestamp
```

### 2.2 Comment autoreply

```
sp_comment_autoreply_enabled         (True|False)
sp_comment_public_enabled            (True|False)
sp_comment_private_enabled           (True|False)
sp_comment_landing_url               (URL)
sp_comment_tg_url                    (URL)
sp_comment_yt_url                    (URL)
sp_comment_private_text              (template з {landing_url}/{tg_url}/{yt_url})
sp_comment_hide_spam_enabled         (True|False)
```

### 2.3 Facebook / Instagram

```
fb_page_access_token                 (legacy Page Token)
fb_app_id                            (Meta App ID)
fb_app_secret                        (Meta App Secret)
fb_token_status                      (обчислюється cron-ом)
fb_token_last_check                  (обчислюється cron-ом)
fb_token_expires_at                  (обчислюється cron-ом)
ig_user_id                           (legacy IG Business ID)
```

### 2.4 LLM

```
llm_classifier_enabled               (True|False)
anthropic_api_key                    (sk-ant-api03-...)
llm_model                            (claude-haiku-4-5)
```

### 2.5 Telegram

```
telegram_alerts_enabled              (True|False)
telegram_bot_token                   (123456:AAEr-...)
telegram_chat_id                     (e.g. -1001234567890)
```

### 2.6 Auto-greeting

```
new_contact_greeting                 (текст першого авто-привітання)
new_contact_greeting2                (текст другого авто-привітання, опційно)
```

### 2.7 Deprecated (не використовуються)

```
ai_filter_enabled                    — стара Gemini-binary класифікація (замінена на Anthropic 8-кат)
ai_api_key                           — там же
ai_base_url                          — там же
ai_model                             — там же
```

Можна видалити через odoo shell якщо мішають:
```python
env['ir.config_parameter'].sudo().search([
    ('key', 'in', ['odoo_chatwoot_connector.ai_filter_enabled',
                   'odoo_chatwoot_connector.ai_api_key',
                   'odoo_chatwoot_connector.ai_base_url',
                   'odoo_chatwoot_connector.ai_model'])
]).unlink()
```

---

## 3. Facebook Pages (multi-page)

### 3.1 Модель `sendpulse.facebook.page`

Кожна запис — одна FB-сторінка з її Page Token.

| Поле | Призначення |
|---|---|
| `name` | Людиночитана назва |
| `page_id` | FB Page ID (унікальний, індексований) |
| `access_token` | Безстроковий Page Token |
| `ig_business_id` | Instagram Business Account ID (якщо приєднаний) |
| `category` | З /me/accounts |
| `is_default` | Fallback для webhook-ів без page_id або коли Page не знайдена |
| `active` | Якщо False — не використовується у lookup |
| `landing_url` / `tg_url` / `yt_url` | Per-page override шаблонів |
| `token_status` | Оновлюється cron-ом |
| `last_checked_at` | Оновлюється cron-ом |

### 3.2 Як додати Pages

**Автоматично (рекомендовано):** через Settings → Multi-page → кнопка «Синхронізувати з Meta /me/accounts».

Потрібен **короткоживучий User Access Token**:
1. https://developers.facebook.com/tools/explorer/
2. Application: **твоя FB App**
3. User Token → Add permissions: `pages_show_list` + `business_management` (+ `pages_read_engagement` для категорії)
4. Generate Access Token → авторизувати → copy
5. Вставити у поле «User Access Token» у Settings → «Синхронізувати»

Результат: для кожної сторінки де ти — адмін, створиться запис з **безстроковим Page Token**.

**Вручну:** Меню «SendPulse → Facebook Pages» → кнопка New → заповнити `name`, `page_id`, `access_token`, `ig_business_id`.

### 3.3 Default Page

Потрібна **одна** сторінка з `is_default=True` як fallback. Constraint automatically resets old default при встановленні нового.

### 3.4 Token resolution priority у `_get_fb_page_token`

```
1. page.access_token          (якщо передано явно)
2. Page за self.sp_page_id    (для повторних операцій у тій самій розмові)
3. Default Page               (is_default=True, active=True)
4. Legacy fb_page_access_token (`ir.config_parameter`)
```

---

## 4. Cron schedule

**Файл:** `data/clean_data_cron.xml` (всі cron-и `active=True`, `numbercall=-1`).

| Cron | Метод | Interval | Наступний запуск (default) |
|---|---|---|---|
| Очищення webhook даних | `sendpulse.webhook.data.cron_clean` | 1d | — |
| Авто-синхронізація Discuss каналів | `sendpulse.connect.cron_sync_discuss_channels` | 1h | — |
| Повернення втрачених контактів | `sendpulse.connect.cron_pull_missing_contacts` | 6h | — |
| Перевірка FB Page Access Token | `sendpulse.connect.cron_check_fb_token_expiry` | 7d | 2026-04-19 06:00 UTC |
| Попередження про закриття 24h вікна | `sendpulse.connect.cron_check_messenger_windows` | 30m | 2026-04-19 10:00 UTC |

### 4.1 Ручний виклик з odoo shell

```bash
ssh server
docker exec -i <odoo_web> /usr/bin/odoo shell -d <db> --no-http << 'EOF'
env['sendpulse.connect'].sudo().cron_check_fb_token_expiry()
env.cr.commit()
EOF
```

---

## 5. Groups & permissions

**Файл:** `security/security.xml`.

| Group | XMLID | Призначення |
|---|---|---|
| SendPulse Odoo / Officer | `odoo_chatwoot_connector.group_sendpulse_officer` | Бачить свої розмови (`user_id = current_user`) |
| SendPulse Odoo / Administrator | `odoo_chatwoot_connector.group_sendpulse_admin` | Повний доступ |

**Record rule** на `sendpulse.connect`:

```xml
<field name="domain_force">[('user_id', '=', user.id)]</field>  <!-- officer -->
<field name="domain_force">[(1, '=', 1)]</field>                 <!-- admin -->
```

### 5.1 Додавання оператора

1. Settings → Users & Companies → Users → [user] → Access Rights
2. «SendPulse Odoo» → виставити `Officer` або `Administrator`
3. Save

Без цієї групи користувач **не бачить** SendPulse меню.

---

## 6. Webhook setup у SendPulse

Шлях у SendPulse UI: Chatbots → ваш бот → Settings → Webhooks → **+ Add Webhook**.

### 6.1 URL

Значення з поля **Webhook URL** у Odoo Settings → SendPulse. Формат:
```
https://<your-domain>/sendpulse/webhook
```

### 6.2 Events (check все)

- ✅ `subscribed` — нова підписка на бота
- ✅ `incoming_message` — повідомлення або коментар від клієнта
- ✅ `open_chat` — відкриття чату
- ✅ `unsubscribed` — відписка
- ✅ `outgoing_message` — якщо SendPulse сам шле (для dedup з Odoo)

### 6.3 Authentication

SendPulse додає HMAC-SHA256 signature у header `X-SendPulse-Signature` з секретом = `webhook_token` у Settings. Controller перевіряє перед обробкою.

---

## 7. Meta App setup

### 7.1 Створення App

1. https://developers.facebook.com/apps/ → Create App
2. Use case: **Other** → Business App
3. Type: **Business**
4. Display name: напр. `<BusinessName>_odoo`
5. Business Manager: вибрати ваш BM

### 7.2 Потрібні permissions (для App Review)

- `pages_show_list` — list Pages адміна
- `pages_read_engagement` — read post content, metadata
- `pages_read_user_content` — read user comments (auto-injected з `pages_manage_engagement`)
- `pages_manage_engagement` — **public reply** під коментарем
- `pages_messaging` — **private reply** у Messenger
- `pages_manage_metadata` — webhook subscriptions + hide_comment
- `business_management` — /me/accounts with manager-level data
- `instagram_business_basic` — (former `instagram_basic`)
- `instagram_manage_comments` — public reply під IG
- `instagram_business_manage_messages` — (former `instagram_manage_messages`)

### 7.3 App Review

Потрібен для **Advanced Access** — інакше токен працює тільки для адмінів App.

Процес: ~3-7 днів. Деталі у `project_campscout_meta_app_review.md` (memory).

### 7.4 System User / Page Token

Після approval:
1. Business Settings → System Users → Create System User
2. Assigned Pages → Add Pages (усі потрібні)
3. Assigned Apps → Add App
4. Generate Token → Tokens Permissions → всі ^^
5. Token Never Expires (якщо System User)
6. Copy token у `sendpulse.facebook.page.access_token` (CampScout default)

**Альтернатива** (якщо не хочеш System User): User Token з Graph Explorer → exchange на long-lived через `/oauth/access_token` → /me/accounts → Page Tokens успадковують expiry.

---

## 8. Receipts / checklist

### 8.1 Мінімальне налаштування для прийому DM

- [x] `client_id`, `client_secret`, `webhook_token` — заповнені
- [x] Webhook у SendPulse створений, URL правильний
- [x] Бот у SendPulse підключений (Telegram/IG/FB/WhatsApp)
- [x] Принаймні один оператор з `group_sendpulse_officer`

### 8.2 Для автовідповідей на коменти FB/IG

- [x] Мінімум + Meta App з Advanced Access approved
- [x] Хоча б одна `sendpulse.facebook.page` з робочим токеном
- [x] `is_default=True` встановлено на одній з них
- [x] `sp_comment_autoreply_enabled=True`

### 8.3 Для LLM-класифікації

- [x] `llm_classifier_enabled=True`
- [x] `anthropic_api_key` заповнено
- [x] (Опціонально) `sp_comment_hide_spam_enabled=True`

### 8.4 Для Telegram-алертів

- [x] Бот у @BotFather створений
- [x] Додано у групу менеджерів
- [x] `telegram_alerts_enabled=True` + token + chat_id

### 8.5 Для точного token expiry tracking

- [x] `fb_app_id` + `fb_app_secret` заповнені

### 8.6 Smoke test

```bash
# Перевірка стану
docker exec <db> psql -U odoo -d <db> -c "
SELECT key, CASE WHEN length(value) > 30 THEN substring(value, 1, 20) || '...' ELSE value END
FROM ir_config_parameter
WHERE key LIKE 'odoo_chatwoot_connector.%'
ORDER BY key;
"

# Тест Telegram (з odoo shell)
env['sendpulse.connect'].sudo()._notify_telegram('✅ Test', silent=False)

# Тест LLM
env['sendpulse.connect'].sudo()._classify_comment('Яка ціна?', 'facebook')
# → 'question_price'

# Тест Graph API
import requests
p = env['sendpulse.facebook.page'].sudo().search([('is_default', '=', True)], limit=1)
r = requests.get(f'https://graph.facebook.com/v25.0/me', params={'access_token': p.access_token, 'fields': 'id,name'})
r.status_code  # → 200
```

---

*Оновлюється при додаванні нових параметрів. Актуальна версія прив'язана до релізу модуля.*
