# SendPulse Odo — Технічна документація

> Версія документації: 1.0.0
> Дата: 2026-03-26
> Автор модуля: Volodymyr Shevchenko
> Ліцензія: LGPL-3

---

## Зміст

1. [Огляд модуля](#1-огляд-модуля)
2. [Архітектура системи](#2-архітектура-системи)
3. [Моделі даних](#3-моделі-даних-детально)
4. [Webhook — детальний опис](#4-webhook--детальний-опис)
5. [Ідентифікація клієнтів](#5-ідентифікація-клієнтів)
6. [Двостороннє спілкування](#6-двостороннє-спілкування)
7. [SendPulse API](#7-sendpulse-api)
8. [Odoo Discuss інтеграція](#8-odoo-discuss-інтеграція)
9. [Картка партнера — що відображається](#9-картка-партнера--що-відображається)
10. [Права доступу](#10-права-доступу)
11. [Налаштування (конфігурація)](#11-налаштування-конфігурація)
12. [Встановлення та розгортання](#12-встановлення-та-розгортання)
13. [UTM джерела](#13-utm-джерела)
14. [Cron задачі](#14-cron-задачі)
15. [Відомі обмеження та TODO](#15-відомі-обмеження-та-todo)

---

## 1. Огляд модуля

### Призначення

**SendPulse Odo** — модуль двосторонньої інтеграції між Odoo 17 та платформою SendPulse (чат-боти месенджерів). Він дозволяє операторам підтримки отримувати повідомлення від клієнтів із різних соціальних мереж прямо в Odoo Discuss, відповідати клієнтам без виходу з Odoo, а також автоматично прив'язувати переписку до картки клієнта (res.partner).

Технічна назва модуля: `odoo_chatwoot_connector`
Версія: `17.0.1.0.0`
Категорія: `Discuss`
Репозиторій: https://github.com/VladSh77/odoo-chatwoot-connector

### Версія, залежності

**Залежності Odoo-модулів:**

| Модуль | Призначення |
|--------|-------------|
| `mail` | Базова інфраструктура Discuss/чатів |
| `contacts` | Модель res.partner для картки клієнта |
| `crm` | UTM-джерела (utm.source) для атрибуції каналів |
| `web` | Базовий веб-фреймворк Odoo |

**Залежності Python:**

| Пакет | Призначення |
|-------|-------------|
| `requests` | HTTP-запити до SendPulse REST API |

### Ключові можливості

- Отримання подій (повідомлень) від SendPulse через Webhook у реальному часі
- Автоматична ідентифікація клієнтів за email, телефоном або SendPulse Contact ID
- Збереження повної двосторонньої історії розмов у картці партнера
- Підтримка каналів: **Telegram, Instagram, Facebook, Messenger, Viber, WhatsApp, TikTok, LiveChat**
- Черга нових та неідентифікованих чатів для операторів
- Відповідь клієнту прямо з Odoo Discuss (повідомлення летить назад у SendPulse)
- Надсилання вкладень (фото, файли) через SendPulse API
- Сповіщення операторів через Odoo bus (спливаючі повідомлення)
- UTM-атрибуція джерела першого контакту по кожному каналу
- Розмежування доступу: Officer (свої чати) vs Administrator (всі чати)
- Автоматичне очищення сирих webhook-даних старших за 7 днів (cron)
- Збереження сирого JSON кожного webhook-запиту для діагностики

---

## 2. Архітектура системи

### Діаграма потоку даних (ASCII art)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                         ЗОВНІШНЯ СТОРОНА                                    ║
║                                                                              ║
║   [Telegram]  [Instagram]  [Facebook]  [Viber]  [WhatsApp]  [TikTok]        ║
║        │           │           │          │          │          │            ║
║        └───────────┴───────────┴──────────┴──────────┴──────────┘           ║
║                                    │                                         ║
║                              [SendPulse]                                     ║
║                           Платформа чат-ботів                               ║
╚════════════════════════════════════╪═════════════════════════════════════════╝
                                     │  HTTP POST JSON (Webhook)
                                     │  POST /sendpulse/webhook
                                     ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║                              ODOO SERVER                                    ║
║                                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │  controllers/main.py  —  SendpulseWebhookController                 │    ║
║  │  • Приймає JSON payload                                              │    ║
║  │  • Логує сирі дані у sendpulse.webhook.data                         │    ║
║  │  • Ігнорує вихідні (outbound_message)                               │    ║
║  │  • Маршрутизує по event_type                                        │    ║
║  └──────────────────────────┬──────────────────────────────────────────┘    ║
║                             │                                                ║
║              ┌──────────────┼──────────────────┐                           ║
║              │              │                   │                           ║
║              ▼              ▼                   ▼                           ║
║  [incoming_message]   [new_subscriber]   [bot_unsubscribe]                 ║
║  [opened_live_chat]                                                          ║
║              │              │                   │                           ║
║              └──────────────┘                   │                           ║
║                     │                           │                           ║
║                     ▼                           ▼                           ║
║  ┌──────────────────────────────┐  ┌─────────────────────────────────┐      ║
║  │  sendpulse.connect           │  │  _process_unsubscribe()         │      ║
║  │  _process_incoming_event()   │  │  stage → 'close'                │      ║
║  │                              │  └─────────────────────────────────┘      ║
║  │  1. _find_partner()          │                                            ║
║  │     ├── sendpulse_contact_id │                                            ║
║  │     ├── email (ilike)        │                                            ║
║  │     └── phone/mobile        │                                            ║
║  │                              │                                            ║
║  │  2. Знайти/створити          │                                            ║
║  │     sendpulse.connect        │                                            ║
║  │                              │                                            ║
║  │  3. Зберегти                 │                                            ║
║  │     sendpulse.message        │                                            ║
║  │                              │                                            ║
║  │  4. _update_partner_source() │                                            ║
║  │     → partner.sendpulse      │                                            ║
║  │       .channel               │                                            ║
║  │                              │                                            ║
║  │  5. Пост у discuss.channel   │                                            ║
║  │     (якщо є)                 │                                            ║
║  └──────────────────────────────┘                                            ║
║          │                │                                                  ║
║          ▼                ▼                                                  ║
║  ┌───────────────┐  ┌─────────────────────────────────────────────────┐     ║
║  │ res.partner   │  │  discuss.channel  (тип: group)                  │     ║
║  │ (картка       │  │  • З'являється у Discuss (дзвіночок)            │     ║
║  │  клієнта)     │  │  • Оператор пише тут → message_post override   │     ║
║  │               │  │  • Override надсилає повідомлення назад у API  │     ║
║  │  sendpulse    │  └────────────────────────┬────────────────────────┘     ║
║  │  _channel_ids │                           │                              ║
║  │  _message_ids │                           │ HTTP POST                    ║
║  └───────────────┘                           │ Bearer token                 ║
║                                              ▼                              ║
║                                   ┌─────────────────────┐                   ║
║                                   │  SendPulse REST API  │                   ║
║                                   │  /contacts/send      │                   ║
║                                   └──────────┬──────────┘                   ║
╚═════════════════════════════════════════════╪════════════════════════════════╝
                                              │
                                              ▼
                                    [Клієнт отримує
                                     повідомлення у
                                     месенджері]
```

### Опис взаємодії компонентів

| Компонент | Роль |
|-----------|------|
| `controllers/main.py` | Точка входу webhook. Приймає POST JSON від SendPulse, зберігає сирі дані, маршрутизує події |
| `models/sendpulse_connect.py` | Центральна бізнес-логіка. Обробка подій, ідентифікація партнерів, API-відправка |
| `models/sendpulse_message.py` | Зберігання повідомлень, webhook-сирих даних, каналів партнера |
| `models/mail_channel.py` | Override `discuss.channel.message_post` — перехоплює відповіді операторів і надсилає їх через API |
| `models/res_partner.py` | Розширення картки партнера: поля, лічильники, смарт-кнопки |
| `models/res_config_settings.py` | Конфігурація OAuth та webhook URL |
| `security/security.xml` | Групи Officer/Administrator та record rules |
| `data/clean_data_cron.xml` | Cron-задача очищення webhook-даних |
| `data/sendpulse_utm_data.xml` | UTM-джерела для кожного каналу |

---

## 3. Моделі даних (детально)

### 3.1 `sendpulse.connect`

**Файл:** `models/sendpulse_connect.py`
**Опис:** Центральна модель. Кожен запис — одна активна розмова між клієнтом і ботом SendPulse. До розмови прив'язані: партнер Odoo, discuss.channel для операторів, список повідомлень.
**Порядок сортування:** `write_date desc`

#### Поля

| Поле | Тип | Обов'язкове | Опис |
|------|-----|-------------|------|
| `name` | `Char` | Так | Ім'я контакту (з SendPulse) |
| `partner_id` | `Many2one(res.partner)` | Ні | Ідентифікований партнер Odoo. Якщо порожньо — розмова в черзі неідентифікованих |
| `stage` | `Selection` | Так | Статус розмови: `new`, `in_progress`, `new_message`, `close` |
| `service` | `Selection` | Ні | Канал: `telegram`, `instagram`, `facebook`, `messenger`, `viber`, `whatsapp`, `tiktok`, `livechat` |
| `sendpulse_contact_id` | `Char` | Ні | UUID контакту в SendPulse. Головний ключ ідентифікації (індексований) |
| `bot_id` | `Char` | Ні | ID бота в SendPulse |
| `bot_name` | `Char` | Ні | Назва бота |
| `last_message_preview` | `Char` | Ні | Текст останнього повідомлення (до 100 символів) |
| `last_message_date` | `Datetime` | Ні | Дата та час останнього повідомлення |
| `social_username` | `Char` | Ні | Username або профіль у соцмережі |
| `social_profile_url` | `Char` | Ні | Пряме посилання на профіль (Facebook, Instagram тощо) |
| `unidentified_email` | `Char` | Ні | Email з SendPulse до моменту ідентифікації партнера |
| `unidentified_phone` | `Char` | Ні | Телефон з SendPulse до моменту ідентифікації |
| `channel_id` | `Many2one(discuss.channel)` | Ні | Пов'язаний канал Odoo Discuss |
| `user_ids` | `Many2many(res.users)` | Ні | Оператори, призначені на цю розмову |
| `message_ids` | `One2many(sendpulse.message)` | Ні | Список усіх повідомлень розмови |
| `message_count` | `Integer` | Ні | Обчислюване: кількість повідомлень |
| `last_notified_at` | `Datetime` | Ні | Час останнього сповіщення оператора (throttle) |
| `source_id` | `Many2one(utm.source)` | Ні | UTM-джерело розмови |
| `is_unidentified` | `Boolean` | Ні | Обчислюване (store=True): True якщо `partner_id` порожній |
| `service_icon` | `Char` | Ні | Обчислюване: emoji-іконка каналу для відображення в списку |

#### Статуси розмови (Stage)

| Значення | Відображення | Колір у списку |
|----------|-------------|----------------|
| `new` | Новий | Червоний (danger) |
| `in_progress` | В роботі | Зелений (success) |
| `new_message` | Нове повідомлення | Жовтий (warning) |
| `close` | Закрито | Сірий (muted) |

#### Ключові методи

| Метод | Тип | Опис |
|-------|-----|------|
| `action_open_discuss()` | instance | Відкриває discuss.channel для цієї розмови. Якщо каналу немає — створює. Додає поточного користувача як учасника |
| `action_identify_partner()` | instance | Відкриває форму ідентифікації клієнта у pop-up |
| `action_close()` | instance | Змінює stage на `close`, викликає `_post_history_to_partner()` |
| `action_reopen()` | instance | Змінює stage на `in_progress` |
| `_create_discuss_channel()` | instance | Створює `discuss.channel` типу `group`. Постить в нього всю існуючу історію повідомлень. Додає операторів |
| `_post_history_to_partner()` | instance | Переносить всі повідомлення з `sendpulse.message` у `partner.sendpulse.message` для відображення у вкладці Messaging картки партнера |
| `assign_partner(partner_id)` | instance | Прив'язує ідентифікованого партнера, переносить історію, оновлює UTM |
| `_update_partner_source()` | instance | Створює або оновлює запис `partner.sendpulse.channel` для партнера. Збільшує лічильник повідомлень через raw SQL |
| `_notify_operators_new_conversation()` | instance | Надсилає bus-сповіщення всім користувачам групи Officer |
| `_notify_operators_new_message()` | instance | Надсилає bus-сповіщення з throttle 1 раз на годину |
| `_get_access_token()` | instance | OAuth2: отримує Bearer token від `api.sendpulse.com/oauth/access_token` |
| `send_message_to_sendpulse(text, attachment_url)` | instance | Надсилає текст та/або вкладення клієнту через SendPulse REST API |
| `_process_incoming_event(data, contact, bot, service, event_type, timestamp_ms)` | `@api.model` | Головний обробник вхідних webhook-подій. 5 кроків (детально в розділі 4) |
| `_find_partner(contact_id, email, phone)` | `@api.model` | Ідентифікація партнера за трьома пріоритетами |
| `_process_unsubscribe(contact_id, service)` | `@api.model` | Закриває всі активні розмови при відписці клієнта |

---

### 3.2 `sendpulse.message`

**Файл:** `models/sendpulse_message.py`
**Опис:** Зберігає окремі повідомлення прив'язані до розмови `sendpulse.connect`. Є основним сховищем хронологічного лога переписки з SendPulse.
**Порядок сортування:** `date asc`

#### Поля

| Поле | Тип | Обов'язкове | Опис |
|------|-----|-------------|------|
| `name` | `Char` | Ні | Мітка часу у форматі `YYYY-MM-DD HH:MM` |
| `date` | `Datetime` | Ні | Дата повідомлення (за замовчуванням — now) |
| `raw_json` | `Text` | Ні | Сирий JSON/dict як рядок для збереження оригінальних даних |
| `sendpulse_contact_id` | `Char` | Ні | UUID контакту SendPulse (денормалізація для зручності) |
| `connect_id` | `Many2one(sendpulse.connect)` | Ні | Батьківська розмова. `ondelete='cascade'` |
| `direction` | `Selection` | Ні | `incoming` (від клієнта) або `outgoing` (від оператора) |
| `message_type` | `Selection` | Ні | `text`, `image`, `file`, `other` |
| `text_message` | `Text` | Ні | Обчислюване (store=True) з `raw_json`. Витягує `text` або `last_message` |
| `attachment_url` | `Char` | Ні | URL вкладення (фото, файл) |

#### Ключові методи

| Метод | Тип | Опис |
|-------|-----|------|
| `_compute_text_message()` | compute | Парсить `raw_json` через `ast.literal_eval`. Витягує ключ `text` або `last_message`. При помилці парсингу повертає весь `raw_json` як текст |

---

### 3.3 `partner.sendpulse.message`

**Файл:** `models/sendpulse_message.py`
**Опис:** Лог повідомлень у вкладці "Messaging" картки партнера. На відміну від `sendpulse.message` — прив'язаний до `res.partner`, а не до розмови. Зберігається при закритті розмови або під час активної переписки.
**Порядок сортування:** `date desc`

#### Поля

| Поле | Тип | Обов'язкове | Опис |
|------|-----|-------------|------|
| `partner_id` | `Many2one(res.partner)` | Так | Партнер. `ondelete='cascade'` |
| `author_id` | `Many2one(res.partner)` | Ні | Автор (оператор) для вихідних повідомлень |
| `date` | `Datetime` | Ні | Дата повідомлення |
| `text_message` | `Html` | Ні | Текст повідомлення у форматі HTML |
| `service` | `Selection` | Ні | Канал (telegram, instagram тощо) |
| `direction` | `Selection` | Ні | `incoming` або `outgoing` |
| `service_label` | `Char` | Ні | Обчислюване: emoji + назва каналу для відображення |

---

### 3.4 `partner.sendpulse.channel`

**Файл:** `models/sendpulse_message.py`
**Опис:** Зберігає список усіх соціальних каналів партнера. Один запис = один канал одного партнера. Якщо клієнт писав з Instagram і Telegram — два окремі записи. Відображається в картці партнера під полем VAT.
**Порядок сортування:** `first_contact_date desc`

#### Поля

| Поле | Тип | Обов'язкове | Опис |
|------|-----|-------------|------|
| `partner_id` | `Many2one(res.partner)` | Так | Партнер. `ondelete='cascade'` |
| `service` | `Selection` | Так | Канал |
| `sendpulse_contact_id` | `Char` | Ні | UUID контакту в SendPulse для цього каналу |
| `social_username` | `Char` | Ні | Username в соцмережі |
| `social_profile_url` | `Char` | Ні | URL профілю (посилання) |
| `first_contact_date` | `Datetime` | Ні | Дата першого контакту (за замовчуванням — now) |
| `last_contact_date` | `Datetime` | Ні | Дата останнього контакту |
| `message_count` | `Integer` | Ні | Лічильник повідомлень (інкрементується raw SQL) |
| `source_id` | `Many2one(utm.source)` | Ні | UTM-джерело |
| `display_name_computed` | `Char` | Ні | Обчислюване (store=True): "Telegram (@username)" або "Facebook (url)" |

#### SQL constraint

```sql
UNIQUE(partner_id, service, sendpulse_contact_id)
```
Запобігає дублюванню запису одного каналу для одного партнера.

---

### 3.5 `sendpulse.webhook.data`

**Файл:** `models/sendpulse_message.py`
**Опис:** Таблиця для зберігання сирих JSON-даних кожного webhook-запиту від SendPulse. Використовується для діагностики та відлагодження. Автоматично очищується cron-задачею через 7 днів.
**Порядок сортування:** `create_date desc`

#### Поля

| Поле | Тип | Опис |
|------|-----|------|
| `name` | `Char` | Ім'я контакту з payload |
| `sendpulse_contact_id` | `Char` | UUID контакту |
| `service` | `Selection` | Канал |
| `event_type` | `Char` | Тип події (`incoming_message`, `new_subscriber` тощо) |
| `raw_data` | `Text` | Повний JSON payload як рядок |
| `bot_id` | `Char` | ID бота |
| `bot_name` | `Char` | Назва бота |

#### Ключові методи

| Метод | Тип | Опис |
|-------|-----|------|
| `clear_old_webhooks()` | instance | Видаляє записи старші за 7 днів. Викликається cron-задачею кожні 7 днів |

---

### 3.6 `res.partner` (розширення)

**Файл:** `models/res_partner.py`
**Опис:** Розширює стандартну модель партнера Odoo полями та методами для інтеграції з SendPulse.

#### Додані поля

| Поле | Тип | Опис |
|------|-----|------|
| `sendpulse_contact_id` | `Char` | UUID контакту в SendPulse. Індексовано. Первинний ключ для ідентифікації |
| `sendpulse_channel_ids` | `One2many(partner.sendpulse.channel)` | Всі соціальні канали партнера |
| `sendpulse_channel_count` | `Integer` | Кількість каналів (обчислюване) |
| `sendpulse_connect_ids` | `One2many(sendpulse.connect)` | Всі розмови партнера |
| `sendpulse_connect_count` | `Integer` | Кількість розмов (обчислюване, для смарт-кнопки) |
| `sendpulse_message_ids` | `One2many(partner.sendpulse.message)` | Повідомлення для вкладки Messaging |

#### Додані методи

| Метод | Опис |
|-------|------|
| `action_open_sendpulse_connects()` | Відкриває список розмов SendPulse для цього партнера (domain by partner_id) |

---

### 3.7 `res.config.settings` (розширення)

**Файл:** `models/res_config_settings.py`
**Опис:** Розширює форму налаштувань Odoo (Settings → Technical) для конфігурації інтеграції SendPulse.

#### Додані поля

| Поле | Тип | config_parameter | Опис |
|------|-----|-----------------|------|
| `sendpulse_client_id` | `Char` | `sendpulse_odo.client_id` | Client ID з SendPulse API |
| `sendpulse_client_secret` | `Char` | `sendpulse_odo.client_secret` | Client Secret з SendPulse API |
| `sendpulse_webhook_token` | `Char` | `sendpulse_odo.webhook_token` | Секретний токен для валідації запитів |
| `sendpulse_webhook_url` | `Char` | — | Обчислюване (readonly): URL для вставки в SendPulse |

#### Обчислення Webhook URL

```python
f"{base_url}/sendpulse/webhook"
# Наприклад: https://crm.mycompany.com/sendpulse/webhook
```

---

### 3.8 `discuss.channel` (розширення)

**Файл:** `models/mail_channel.py`
**Опис:** Ключове розширення для двостороннього спілкування. Override методу `message_post` дозволяє перехоплювати повідомлення оператора в Discuss і надсилати їх через SendPulse API.

#### Додані поля

| Поле | Тип | Опис |
|------|-----|------|
| `sendpulse_connect_id` | `Many2one(sendpulse.connect)` | Прив'язка до розмови SendPulse. `ondelete='set null'` |

#### Ключові методи

| Метод | Тип | Опис |
|-------|-----|------|
| `sendpulse_channel_get(env, partner_ids, connect_id, operator_partner_id)` | classmethod | Створює discuss.channel для SendPulse розмови |
| `message_post(**kwargs)` | override | Перехоплює відправку. Якщо канал прив'язаний до SendPulse розмови — надсилає через API. Фільтрує системні повідомлення та incoming (щоб уникнути дублювання) |
| `_is_system_message(text)` | instance | Перевіряє за regex-патернами чи є повідомлення системним (joined/left/invited/приєднав/покинув/запросив) |
| `_get_attachment_url(attachment_id)` | instance | Генерує публічний URL вкладення з токеном доступу: `{base_url}/web/content/{id}?access_token={token}` |
| `action_unfollow()` | override | Забороняє покидати активний SendPulse-канал без закриття розмови. При закритому чаті — видаляє користувача з операторів |

---

## 4. Webhook — детальний опис

### URL endpoint

```
POST /sendpulse/webhook
```

**Параметри маршруту:**
- `type='json'` — Odoo автоматично парсить тіло запиту як JSON
- `auth='public'` — не потребує авторизації Odoo (доступний публічно)
- `csrf=False` — захист CSRF вимкнено (для зовнішніх webhook-викликів)
- `methods=['POST']` — тільки POST-запити

### Підтримувані події

| Назва події (`title`) | Константа в коді | Опис |
|----------------------|------------------|------|
| `new_subscriber` | `EVENT_NEW_SUBSCRIBER` | Перший контакт клієнта з ботом — клієнт підписався |
| `incoming_message` | `EVENT_INCOMING_MSG` | Клієнт написав повідомлення боту |
| `outbound_message` | `EVENT_OUTGOING_MSG` | Бот/оператор відправив повідомлення (ігнорується — щоб уникнути петлі) |
| `opened_live_chat` | `EVENT_LIVE_CHAT` | Клієнт ініціював live-чат |
| `bot_unsubscribe` | `EVENT_UNSUBSCRIBE` | Клієнт відписався від бота |
| `bot_blocked` | `EVENT_BLOCKED` | Клієнт заблокував бота (подія логується, але не обробляється) |

### Структура payload (JSON приклад з усіма полями)

```json
{
  "service": "telegram",
  "title": "incoming_message",
  "bot": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "MyShopBot",
    "external_id": "123456789"
  },
  "contact": {
    "id": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
    "name": "Іван Петренко",
    "email": "ivan@example.com",
    "phone": "+380991234567",
    "last_message": "Доброго дня! Цікавить ваш товар",
    "photo": "https://t.me/i/userpic/...",
    "tags": ["vip", "returning"],
    "variables": {
      "username": "ivanpetrenko",
      "telegram_username": "ivanpetrenko",
      "profile_url": "",
      "facebook_url": "",
      "instagram_url": ""
    }
  },
  "date": 1617401679000
}
```

**Опис полів payload:**

| Поле | Тип | Де використовується |
|------|-----|---------------------|
| `service` | string | Визначення каналу, маршрутизація API |
| `title` | string | Тип події — головний перемикач логіки |
| `bot.id` | string | Зберігається у `sendpulse.connect.bot_id` |
| `bot.name` | string | Зберігається у `sendpulse.connect.bot_name` |
| `contact.id` | string (UUID) | Головний ключ ідентифікації (`sendpulse_contact_id`) |
| `contact.name` | string | Ім'я контакту для відображення |
| `contact.email` | string | Вторинний ключ ідентифікації партнера |
| `contact.phone` | string | Третинний ключ ідентифікації партнера |
| `contact.last_message` | string | Текст повідомлення для збереження |
| `contact.variables.username` | string | Username в соцмережі |
| `contact.variables.profile_url` | string | URL профілю |
| `date` | number (ms) | Timestamp події у мілісекундах |

### Логіка обробки (step by step)

```
1. Контролер приймає POST /sendpulse/webhook
   │
   ├── Перевірка: payload не порожній?
   │   └── Ні → return {'status': 'error', 'message': 'Empty payload'}
   │
   ├── Витягує: event_type, service, contact, bot, timestamp
   │
   ├── ЗАВЖДИ: створює запис sendpulse.webhook.data (сирий лог)
   │
   ├── event_type == 'outbound_message'?
   │   └── Так → return {'status': 'ok', 'skipped': 'outbound'}
   │
   ├── event_type in (new_subscriber, incoming_message, opened_live_chat)?
   │   └── Так → sendpulse.connect._process_incoming_event(...)
   │       │
   │       ├── Крок 1: _find_partner(contact_id, email, phone)
   │       │   ├── Шукаємо по sendpulse_contact_id
   │       │   ├── Шукаємо по email (ilike, case-insensitive)
   │       │   └── Шукаємо по phone/mobile
   │       │
   │       ├── Крок 2: Знайти/створити sendpulse.connect
   │       │   ├── Шукаємо: contact_id + service + stage != 'close'
   │       │   ├── Знайдено → оновлюємо last_message, stage, partner_id
   │       │   └── Не знайдено → create() → _notify_operators_new_conversation()
   │       │
   │       ├── Крок 3: Якщо є last_message → create sendpulse.message
   │       │   ├── direction = 'incoming'
   │       │   ├── Якщо channel_id існує → message_post у discuss.channel
   │       │   └── Якщо partner_id → create partner.sendpulse.message
   │       │
   │       ├── Крок 4: Якщо partner_id → _update_partner_source()
   │       │   ├── Знаходимо UTM source по service
   │       │   ├── Шукаємо partner.sendpulse.channel
   │       │   ├── Знайдено → update last_contact_date + SQL: message_count+1
   │       │   └── Не знайдено → create partner.sendpulse.channel
   │       │
   │       └── Крок 5: Якщо новий і event in (new_subscriber, opened_live_chat)
   │           └── _create_discuss_channel()
   │
   ├── event_type == 'bot_unsubscribe'?
   │   └── Так → _process_unsubscribe(contact_id, service)
   │       └── Всі відкриті розмови → stage = 'close'
   │
   └── return {'status': 'ok'}
```

---

## 5. Ідентифікація клієнтів

### Алгоритм пошуку (пріоритети)

Метод `_find_partner(contact_id, email, phone)` шукає партнера в такому порядку:

```
Пріоритет 1: sendpulse_contact_id
   res.partner WHERE sendpulse_contact_id = contact_id LIMIT 1
   └── Знайдено? → Повертаємо партнера

Пріоритет 2: Email (case-insensitive)
   res.partner WHERE email ILIKE email.strip() LIMIT 1
   └── Знайдено? → Зберігаємо sendpulse_contact_id у партнера
                → Повертаємо партнера

Пріоритет 3: Телефон
   res.partner WHERE phone = clean_phone OR mobile = clean_phone LIMIT 1
   (clean_phone = phone.strip().replace(' ', ''))
   └── Знайдено? → Зберігаємо sendpulse_contact_id у партнера
                → Повертаємо партнера

Нічого не знайдено → Повертаємо None
```

**Важлива поведінка:** При успішному пошуку за email або телефоном (якщо у партнера ще немає `sendpulse_contact_id`) — UUID з SendPulse автоматично зберігається в картці партнера. Це прискорює всі наступні пошуки для цього клієнта.

### Коли створюється новий партнер

Модуль **не створює** нових партнерів автоматично. Якщо партнер не знайдений — розмова зберігається з `partner_id = False` та потрапляє до черги неідентифікованих. Оператор вручну ідентифікує клієнта через кнопку "Ідентифікувати клієнта".

### Черга неідентифікованих

Розмови без партнера доступні через:
- Пункт меню **SendPulse → Нові чати**
- Action `action_sendpulse_connect_unidentified`
- Domain: `[('partner_id', '=', False), ('stage', '!=', 'close')]`

Для таких розмов у формі відображаються поля `unidentified_email` та `unidentified_phone` — дані отримані від SendPulse, але не прив'язані до жодного партнера. Оператор може знайти потрібного партнера вручну або створити нового.

При ідентифікації (виклик `assign_partner(partner_id)`) відбувається:
1. Запис `partner_id` у розмову
2. Перенесення всієї históрії у `partner.sendpulse.message`
3. Оновлення UTM-каналів `partner.sendpulse.channel`
4. Оновлення назви discuss.channel

---

## 6. Двостороннє спілкування

### Вхідні: SendPulse → Odoo flow

```
Клієнт написав у месенджері
         │
         ▼
SendPulse обробляє повідомлення
         │
         ▼ HTTP POST JSON
/sendpulse/webhook
         │
         ▼
Зберігається raw у sendpulse.webhook.data
         │
         ▼
_process_incoming_event()
         │
         ├── Якщо channel_id активний:
         │   connect.channel_id.message_post(
         │     body = "<b>👤 {contact_name}</b>:<br/>{last_message}",
         │     author_id = partner.id або base.partner_root,
         │     message_type = 'comment',
         │   )
         │   Важливо: context['sendpulse_incoming'] = True
         │            (щоб уникнути повторної відправки в API)
         │
         └── Зберігається у partner.sendpulse.message (вкладка Messaging)
```

**Захист від петлі:** При постингу вхідного повідомлення у `discuss.channel` встановлюється контекст `sendpulse_incoming=True`. Override `message_post` перевіряє: якщо `author_id == connect.partner_id.id` — повідомлення не надсилається назад в API (воно вже прийшло від клієнта, не від оператора).

### Вихідні: Odoo → SendPulse flow

```
Оператор пише в discuss.channel
(де sendpulse_connect_id != False)
         │
         ▼
Override: DiscussChannel.message_post()
         │
         ├── Перевірка: sendpulse_connect_id існує?
         ├── Перевірка: НЕ системне повідомлення?
         ├── Перевірка: НЕ incoming від клієнта?
         │
         ▼
html2plaintext(body) → body_plain
         │
         ▼
connect.send_message_to_sendpulse(body_plain, attachment_url)
         │
         ├── _get_access_token() → Bearer token
         │
         ├── endpoint = endpoint_map[service]
         │
         ├── payload = {
         │     'contact_id': sendpulse_contact_id,
         │     'messages': [
         │       {'type': 'text', 'text': {'text': body_plain}}
         │     ]
         │   }
         │
         ▼
POST https://api.sendpulse.com/{service}/contacts/send
         │
         ▼
Клієнт отримує повідомлення у месенджері
         │
Паралельно:
├── create sendpulse.message (direction='outgoing')
└── create partner.sendpulse.message (для вкладки Messaging)
```

### Відправка вкладень

Якщо оператор прикріплює файл у Discuss:

1. `message_post` отримує `attachment_ids=[id, ...]`
2. `_get_attachment_url(attachment_ids[0])` генерує публічний URL:
   ```
   {base_url}/web/content/{att.id}?access_token={att.access_token}
   ```
   Якщо токену немає — генерується через `att.generate_access_token()`
3. До payload додається другий елемент масиву `messages`:
   ```json
   {
     "type": "image",
     "image": {"url": "https://..."}
   }
   ```
4. SendPulse надсилає зображення клієнту

**Обмеження:** Обробляється лише перший вкладений файл (`attachment_ids[0]`). Тип завжди `image` незалежно від реального типу файлу.

---

## 7. SendPulse API

### Авторизація (OAuth2)

Модуль використовує схему OAuth2 Client Credentials:

```
POST https://api.sendpulse.com/oauth/access_token
Content-Type: application/json

{
  "grant_type": "client_credentials",
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET"
}

Response:
{
  "access_token": "eyJhbGciOiJSUzI1NiJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

Отриманий токен використовується у заголовку:
```
Authorization: Bearer {access_token}
```

**Важливо:** Токен запитується при кожній відправці повідомлення (немає кешування). Timeout запиту токена: 10 секунд.

### Ендпоінти по каналах (відправка повідомлень)

| Канал | `service` | API Endpoint |
|-------|-----------|-------------|
| Telegram | `telegram` | `https://api.sendpulse.com/telegram/contacts/send` |
| Instagram | `instagram` | `https://api.sendpulse.com/instagram/contacts/send` |
| Facebook | `facebook` | `https://api.sendpulse.com/facebook/contacts/send` |
| Messenger | `messenger` | `https://api.sendpulse.com/facebook/contacts/send` (той самий, що Facebook) |
| Viber | `viber` | `https://api.sendpulse.com/viber/contacts/send` |
| WhatsApp | `whatsapp` | `https://api.sendpulse.com/whatsapp/contacts/send` |
| LiveChat | `livechat` | `https://api.sendpulse.com/livechat/contacts/send` |
| TikTok | `tiktok` | Fallback на Telegram endpoint (не визначено окремо) |

**Тіло запиту відправки:**
```json
{
  "contact_id": "uuid-контакту-sendpulse",
  "messages": [
    {
      "type": "text",
      "text": {
        "text": "Текст повідомлення оператора"
      }
    },
    {
      "type": "image",
      "image": {
        "url": "https://odoo.example.com/web/content/123?access_token=abc"
      }
    }
  ]
}
```

Timeout запиту на відправку: 15 секунд.

### Обробка помилок

| Ситуація | Поведінка |
|----------|-----------|
| `client_id` або `client_secret` не налаштовані | `_get_access_token()` повертає `None`, логується warning |
| Помилка отримання токена (мережа, 4xx, 5xx) | Логується error, метод повертає `False` |
| Помилка відправки повідомлення | `resp.raise_for_status()` → Exception → логується error, метод повертає `False` |
| Помилка webhook-обробника | Виняток перехоплюється в контролері, логується error з traceback, повертається `{'status': 'error', 'message': str(e)}` |
| Помилка отримання URL вкладення | Логується warning, `attachment_url = None`, відправляється тільки текст |

---

## 8. Odoo Discuss інтеграція

### Як розмови з'являються у дзвіночку

При вхідному повідомленні (`incoming_message`) або новому підписнику (`new_subscriber`) для відповідного `sendpulse.connect`:

1. Якщо `channel_id` ще не існує і подія — `new_subscriber` або `opened_live_chat`:
   → викликається `_create_discuss_channel()`
2. Якщо `channel_id` вже існує:
   → повідомлення постується через `message_post` у discuss.channel
3. Після POST у discuss.channel Odoo автоматично надсилає bus-сповіщення всім учасникам каналу — у них з'являється сповіщення у "дзвіночку" (inbox)

Додатково, при **новій розмові** — `_notify_operators_new_conversation()` надсилає всім користувачам групи `group_sendpulse_officer` спливаюче повідомлення через `bus.bus`:

```json
{
  "title": "SendPulse: Нова розмова",
  "message": "✈️ Іван Петренко: нова розмова з telegram",
  "sticky": false
}
```

При **новому повідомленні** у вже відкритій розмові — `_notify_operators_new_message()` зі throttle 1 раз на годину. Якщо є призначені оператори (`user_ids`) — сповіщення надсилається тільки їм.

### Структура каналу

Кожен `discuss.channel` для SendPulse розмови:

| Параметр | Значення |
|----------|----------|
| `channel_type` | `'group'` — з'являється у Discuss для учасників |
| `name` | `"[TG] Іван Петренко"` (префікс = скорочення сервісу) |
| `description` | `"SendPulse | telegram | @username | email"` |
| `sendpulse_connect_id` | ID пов'язаного `sendpulse.connect` |

**Учасники каналу:** Поточний користувач + всі оператори з `sendpulse.connect.user_ids`.

При першому відкритті розмови (`action_open_discuss`) оператор автоматично додається як учасник якщо його там ще немає.

При **закритті розмови** (`_close_channel`): `discuss.channel.active = False` — канал архівується і зникає з Discuss.

### Захист від системних повідомлень

Override `message_post` фільтрує системні повідомлення Odoo Discuss за regex-патернами. Якщо повідомлення відповідає хоча б одному патерну — воно **не надсилається** в SendPulse API:

| Патерн | Приклад системного повідомлення |
|--------|----------------------------------|
| `joined the channel` | "John joined the channel" |
| `left the channel` | "Jane left the channel" |
| `invited` | "You were invited by..." |
| `приєднав` | "Іван приєднав Марію" |
| `покинув` | "Петро покинув канал" |
| `запросив` | "Адмін запросив оператора" |

---

## 9. Картка партнера — що відображається

### Список каналів (`partner.sendpulse.channel`)

Розташування: під полем **VAT** у формі партнера (inline list).
Видимість: тільки якщо `sendpulse_channel_count > 0`, група `group_sendpulse_officer`.
Редагування: заборонено (`editable=False`, `create=False`, `delete=False`).

Колонки:

| Колонка | Поле | Відображення |
|---------|------|-------------|
| Канал | `service` | Badge з кольорами: Telegram=синій, Instagram/Facebook/Messenger=жовтий, Viber=primary, WhatsApp=зелений |
| Профіль | `social_profile_url` | Клікабельне посилання (widget="url") |
| Username | `social_username` | Текст |
| Останній контакт | `last_contact_date` | Datetime |
| Повідомлень | `message_count` | Число |

### Вкладка Messaging

Розташування: окрема вкладка "Messaging" поруч з вкладкою "Internal Notes".
Видимість: група `group_sendpulse_officer`.
Читання: тільки (`readonly=1`).
Порядок: `date desc` (найновіші зверху).

Колонки:

| Колонка | Поле |
|---------|------|
| Канал | `service_label` (emoji + назва) |
| Від | `direction` (badge: incoming=блакитний, outgoing=зелений) |
| Оператор | `author_id` (optional) |
| Повідомлення | `text_message` (HTML-рендер) |
| Дата | `date` |

### Смарт-кнопка "Розмов"

Розташування: `button_box` поруч з іншими stat-buttons.
Видимість: тільки якщо `sendpulse_connect_count > 0`, група `group_sendpulse_officer`.
Іконка: `fa-comments`.
Дія: `action_open_sendpulse_connects()` — відкриває список розмов з фільтром по поточному партнеру.

---

## 10. Права доступу

### Групи

#### `odoo_chatwoot_connector.group_sendpulse_officer` — Оператор

- Успадковує: `base.group_user` (звичайний внутрішній користувач)
- Бачить: тільки розмови де він призначений (`user_ids contains user`) АБО розмови без операторів (`user_ids = False`)
- Меню: **SendPulse** (всі пункти крім "Webhook Дані")
- Опис: Оператор підтримки

#### `odoo_chatwoot_connector.group_sendpulse_admin` — Адміністратор

- Успадковує: `group_sendpulse_officer` (включає всі права Officer)
- Бачить: **всі** розмови без обмежень
- Меню: **SendPulse → Webhook Дані** (додатково)
- Налаштування: Може змінювати Client ID/Secret, Webhook token

### Правила видимості записів (Record Rules)

| Правило | Модель | Група | Domain |
|---------|--------|-------|--------|
| `odoo_chatwoot_connector.rule_sendpulse_connect_officer` | `sendpulse.connect` | Officer | `['|', ('user_ids', 'in', [user.id]), ('user_ids', '=', False)]` |
| `odoo_chatwoot_connector.rule_sendpulse_connect_admin` | `sendpulse.connect` | Administrator | `[(1, '=', 1)]` (без обмежень) |

### Таблиця доступів до моделей (ir.model.access)

| Модель | Officer (R/W/C/D) | Administrator (R/W/C/D) |
|--------|-------------------|--------------------------|
| `sendpulse.connect` | R, W, -, - | R, W, C, D |
| `sendpulse.message` | R, W, C, D | R, W, C, D |
| `partner.sendpulse.message` | R, W, C, D | R, W, C, D |
| `sendpulse.webhook.data` | -, -, -, D | R, W, C, D |
| `partner.sendpulse.channel` | R, W, C, D | R, W, C, D |

**Примітка:** Officer не може **читати** сирі webhook дані (`sendpulse.webhook.data`), але може їх **видаляти**. Це дозволяє cron-задачі (яка виконується від імені системи) чистити старі записи, при цьому оператори не бачать технічні деталі webhook.

---

## 11. Налаштування (конфігурація)

### Покроковий гайд першого запуску

#### Крок 1 — Отримай API ключі у SendPulse

1. Зайдіть у SendPulse: https://login.sendpulse.com
2. Перейдіть: **Profile → Settings → API** (або **Інтеграції → API**)
3. Знайдіть розділ **API Credentials**
4. Скопіюйте **Client ID** та **Client Secret**
5. Якщо credentials ще немає — натисніть **Generate** або **Create new application**

#### Крок 2 — Заповни форму в Odoo

1. Зайдіть в Odoo → меню **SendPulse → Налаштування**
   (або Settings → SendPulse Odo — потрібна група `group_sendpulse_admin`)
2. Заповніть поля:
   - **SendPulse Client ID** → вставте Client ID з SendPulse
   - **SendPulse Client Secret** → вставте Client Secret
   - **Webhook Secret Token** → придумайте довільний рядок (наприклад: `campscout_sp_2026`)
3. Поле **Webhook URL** заповниться автоматично:
   ```
   https://campscout.eu/sendpulse/webhook
   ```
4. Натисніть **Зберегти**

#### Крок 3 — Налаштуй Webhook у SendPulse

1. У SendPulse перейдіть: **Chatbots → Ваш бот → Settings → Webhooks**
2. Натисніть **Add Webhook**
3. Вставте URL:
   ```
   https://campscout.eu/sendpulse/webhook
   ```
4. Виберіть події для відстеження:
   - ✅ `New subscriber`
   - ✅ `Incoming message`
   - ✅ `Outbound message`
   - ✅ `Opened live chat`
   - ✅ `Bot unsubscribe`
5. Збережіть

#### Крок 4 — Надай доступ операторам

1. Odoo → Settings → Users → відкрий потрібного користувача
2. Знайди секцію **SendPulse Odo**:
   - **Officer** — оператор підтримки (бачить свої чати + непризначені)
   - **Administrator** — адмін (бачить всі чати, налаштування, webhook дані)
3. Збережіть

Після цього меню **SendPulse** з'явиться у лівій навігації для цього користувача.

#### Крок 5 — Перевірка інтеграції

1. Надішліть тестове повідомлення боту SendPulse з Telegram (або іншого каналу)
2. У Odoo → **SendPulse → Нові чати** — має з'явитись новий запис
3. Натисніть **Відкрити чат** — відкриється канал у Discuss
4. Напишіть відповідь у Discuss — клієнт отримає повідомлення у месенджері

---

### Системні параметри

Параметри зберігаються в `ir.config_parameter`. Ключі:

| Ключ | Де встановити | Опис |
|------|--------------|------|
| `odoo_chatwoot_connector.client_id` | SendPulse → Налаштування | OAuth2 Client ID |
| `odoo_chatwoot_connector.client_secret` | SendPulse → Налаштування | OAuth2 Client Secret |
| `odoo_chatwoot_connector.webhook_token` | SendPulse → Налаштування | Секретний токен (резерв для підпису) |
| `web.base.url` | Settings → Technical → System Parameters | Базовий URL Odoo (для генерації webhook URL та attachment URL) |

**Перевірка через shell (якщо потрібна діагностика):**
```python
# Підключитись до Odoo shell всередині контейнера:
# docker exec -it campscout_web odoo shell -d campscout --db_host db --db_user odoo --db_password B2pQiLX190e2yexhmInrPDr5WmEbVv

env['ir.config_parameter'].get_param('odoo_chatwoot_connector.client_id')
env['ir.config_parameter'].get_param('web.base.url')
```

**Встановлення через shell (для автоматизації):**
```python
env['ir.config_parameter'].set_param('odoo_chatwoot_connector.client_id', 'YOUR_CLIENT_ID')
env['ir.config_parameter'].set_param('odoo_chatwoot_connector.client_secret', 'YOUR_SECRET')
env.cr.commit()
```

---

## 12. Встановлення та розгортання

### Вимоги

| Компонент | Версія |
|-----------|--------|
| Odoo | 17.0 (Community або Enterprise) |
| Python | 3.10+ |
| PostgreSQL | 14+ |
| Python пакет `requests` | будь-яка актуальна версія |
| Odoo модулі | `mail`, `contacts`, `crm`, `web` |

### Виробничий сервер (campscout.eu)

**Сервер:** `91.98.122.195`
**Контейнер Odoo:** `campscout_web`
**Шлях до модуля:** `/home/deploy/odoo-prod/custom-addons/odoo_chatwoot_connector`
**Git репозиторій:** https://github.com/VladSh77/odoo-chatwoot-connector
**База даних:** `campscout`

#### Workflow: локально → git → сервер

```
1. Внести зміни локально (/Users/admin/Developer/Fayna-Projects/odoo-chatwoot-connector)
2. git add + git commit + git push origin main
3. На сервері: git pull + оновити модуль в Odoo
```

#### Деплой на сервер (команди)

```bash
# SSH на сервер
ssh deploy@91.98.122.195

# 1. Оновити код з git
sudo git -C /home/deploy/odoo-prod/custom-addons/odoo_chatwoot_connector pull origin main

# 2. Оновити модуль в Odoo (з перезавантаженням views/models)
sudo docker exec campscout_web odoo \
  -u odoo_chatwoot_connector \
  -d campscout \
  --stop-after-init \
  --no-xmlrpc \
  --db_host db --db_port 5432 \
  --db_user odoo \
  --db_password B2pQiLX190e2yexhmInrPDr5WmEbVv

# 3. Перезапустити контейнер
sudo docker restart campscout_web
```

**Якщо змінились views, security або XML-файли** — виконувати кроки 2 і 3.
**Якщо змінився тільки Python-код** — достатньо кроку 3 (docker restart).

#### Кроки встановлення з нуля (новий сервер)

```bash
# 1. Клонувати репозиторій у папку custom-addons
cd /home/deploy/odoo-prod/custom-addons
sudo git clone https://github.com/VladSh77/odoo-chatwoot-connector odoo_chatwoot_connector

# 2. Встановити модуль
sudo docker exec campscout_web odoo \
  -i odoo_chatwoot_connector \
  -d campscout \
  --stop-after-init \
  --no-xmlrpc \
  --db_host db --db_port 5432 \
  --db_user odoo \
  --db_password YOUR_DB_PASSWORD

# 3. Перезапустити контейнер
sudo docker restart campscout_web
```

#### Структура директорії модуля

```
odoo_chatwoot_connector/
├── __manifest__.py
├── __init__.py
├── controllers/
│   ├── __init__.py
│   └── main.py
├── models/
│   ├── __init__.py
│   ├── sendpulse_connect.py
│   ├── sendpulse_message.py
│   ├── mail_channel.py
│   ├── res_partner.py
│   └── res_config_settings.py
├── security/
│   ├── security.xml
│   └── ir.model.access.csv
├── data/
│   ├── sendpulse_utm_data.xml
│   ├── sendpulse_data.xml
│   └── clean_data_cron.xml
├── views/
│   ├── sendpulse_connect_views.xml
│   └── res_partner_views.xml
└── static/
    └── description/
        └── icon.png
```

#### Перегляд логів

```bash
# Логи Odoo в реальному часі
sudo docker logs -f campscout_web | grep -i sendpulse

# Лише помилки
sudo docker logs campscout_web 2>&1 | grep -i "error\|sendpulse"
```

---

## 13. UTM джерела

При першому успішному прив'язуванні партнера до розмови (або при наступних зверненнях) у `partner.sendpulse.channel` записується поле `source_id` з відповідним UTM-джерелом.

### Таблиця: канал → UTM source

| Канал (`service`) | XML ID | Назва UTM |
|------------------|--------|-----------|
| `telegram` | `odoo_chatwoot_connector.utm_source_telegram` | Telegram |
| `instagram` | `odoo_chatwoot_connector.utm_source_instagram` | Instagram |
| `facebook` | `odoo_chatwoot_connector.utm_source_facebook` | Facebook |
| `messenger` | `odoo_chatwoot_connector.utm_source_messenger` | Messenger |
| `viber` | `odoo_chatwoot_connector.utm_source_viber` | Viber |
| `whatsapp` | `odoo_chatwoot_connector.utm_source_whatsapp` | WhatsApp |
| `tiktok` | `odoo_chatwoot_connector.utm_source_tiktok` | TikTok |
| `livechat` | `odoo_chatwoot_connector.utm_source_livechat` | LiveChat |

**Де використовується:** Поле `source_id` у `partner.sendpulse.channel` дозволяє будувати CRM-звіти з розбивкою за каналами залучення. Наприклад: скільки клієнтів прийшли з Telegram vs Instagram.

**Технічна деталь:** UTM-джерела створюються з `noupdate="1"` — вони не перезаписуються при оновленні модуля.

**Резервна поведінка:** Якщо UTM-джерело не знайдено (наприклад, для невідомого сервісу), `source_id = False`. Помилка виключення перехоплюється через `try/except`.

---

## 14. Cron задачі

### Список cron задач

| Назва | XML ID | Модель | Метод | Інтервал |
|-------|--------|--------|-------|----------|
| SendPulse Odo: Очищення старих webhook даних | `ir_cron_sendpulse_clear_webhook_data` | `sendpulse.webhook.data` | `clear_old_webhooks()` | Кожні 7 днів |

### Деталі задачі очищення

**Логіка `clear_old_webhooks()`:**
```python
cutoff = datetime.now() - timedelta(days=7)
old_records = self.search([('create_date', '<', cutoff)])
old_records.unlink()
```

- Видаляє всі записи `sendpulse.webhook.data` старші за 7 днів
- Перша наступна дата запуску після встановлення: `2026-04-01 01:00:00`
- `numbercall = -1` — виконується нескінченно (не зупиняється після N виконань)
- `active = True` — активна за замовчуванням після встановлення

**Управління cron через UI:**
- Settings → Technical → Automation → Scheduled Actions
- Знайти: "SendPulse Odo: Очищення старих webhook даних"
- Можна змінити інтервал або запустити вручну кнопкою "Run Manually"

**Чому 7 днів:** Webhook-дані потрібні для короткострокової діагностики. Зберігання більше тижня недоцільне та займає місце в БД.

---

## 15. Відомі обмеження та TODO

### 24-годинне вікно Facebook / Instagram / Messenger

Платформи Meta (Facebook, Instagram, Messenger) дозволяють надсилати повідомлення клієнту **тільки протягом 24 годин** після його останнього повідомлення. Якщо оператор відповідає пізніше — SendPulse API поверне помилку, але модуль **не відображає цю помилку** в UI Odoo. Оператор може не дізнатися що повідомлення не доставлено.

**Обхідний шлях:** Слідкувати за датою `last_message_date` у картці розмови. Якщо пройшло більше 24 годин з Instagram/Facebook/Messenger — зв'яжіться з клієнтом іншим способом.

**TODO:** Додати валідацію в `send_message_to_sendpulse()` — перевіряти `last_message_date` та показувати попередження оператору при спробі відповіді у метаканалах після 24 годин.

### Telegram як осн��вний канал

Telegram не має 24-годинного обмеження — бот може надсилати повідомлення клієнту в будь-який час після того, як клієнт написав хоча б раз (`/start`). Саме тому Telegram є рекомендованим основним каналом для підтримки через SendPulse Odo.

### Що ще не реалізовано

| Функція | Пріоритет | Опис |
|---------|-----------|------|
| Валідація webhook token | Середній | Поле `sendpulse_webhook_token` зберігається, але не використовується для перевірки підпису запитів |
| Кешування OAuth токена | Середній | Токен запитується при кожній відправці. Слід кешувати в `ir.config_parameter` з терміном дії |
| Підтримка кількох вкладень | Низький | Обробляється тільки `attachment_ids[0]`. При кількох файлах відправляється лише перший |
| TikTok відправка | Низький | Для TikTok використовується fallback на Telegram endpoint — потрібен окремий endpoint |
| Wizard ідентифікації | Середній | `action_identify_partner()` відкриває форму розмови в `identify_mode`, але спеціальної логіки wizard немає |
| Групування статистики | Низький | Немає дашборду чи звітів по кількості чатів / каналів / часу відповіді |
| Підтримка вхідних вкладень | Середній | Вкладення від клієнта (`attachment_url`) зберігається в `sendpulse.message`, але не відображається у discuss.channel як зображення — тільки як посилання |
| Обробка `bot_blocked` | Низький | Подія логується у `sendpulse.webhook.data`, але не змінює статус розмови |
| Автоматичне закриття застарілих розмов | Низький | Немає cron для автозакриття розмов без активності більше N днів |
| Підтримка шаблонів відповідей | Низький | Оператори не можуть використовувати шаблони швидких відповідей у Discuss для SendPulse |

---

## 16. Лог змін — сесія 2026-03-26

### Хронологія виправлень та деплоїв

| Час (UTC) | Коміт | Опис |
|-----------|-------|------|
| 17:51 | `edccb26` | Fix: SendPulse API message payload format (`message` key not `text`) |
| 17:52 | `285b178` | Fix: auto-add all operators to Discuss channels + sync action |
| 17:53 | `535990c` | Fix: replace `%(module.xml_id)d` button with `type=object` (XML ID load order error) |
| 17:54 | `99c28d2` | Fix: remove deprecated `attrs=` attribute (not supported in Odoo 17) |
| 17:55 | `ec203d9` | Fix: show all active (non-closed) conversations by default |
| 18:07 | `72ae5fe` | Fix: prevent duplicate conversations + new SP icon (blue 128×128) |
| 18:08 | `b965f98` | Fix: use correct SendPulse logo (`sendpulse_logo.png`) as module icon |
| 18:15 | `8a15d50` | Fix: add `web_icon` to root menu for home screen app tile |

### Виправлені баги

#### 1. Порожній список "Всі розмови" за замовчуванням
**Проблема:** `search_default_filter_new` фільтрував `stage='new'`, але всі розмови одразу переходять у `in_progress` при створенні каналу → список завжди порожній.
**Рішення:** Замінено на `domain=[('stage','!=','close')]` у action.

#### 2. Реальні клієнтські чати відсутні у Discuss
**Причина:** `_create_discuss_channel()` викликається через `sudo()` → `self.env.user` = OdooBot. Якщо `group_sendpulse_officer` не має призначених користувачів → до каналу додається лише OdooBot.
**Рішення:**
- Збираємо партнерів з обох груп (officer + admin)
- Fallback: всі внутрішні активні користувачі
- Явно виключаємо OdooBot (`base.partner_root`)

#### 3. Дублікати розмов для одного реального клієнта
**Причина:** Пошук розмови ведеться тільки по `sendpulse_contact_id + service`. Якщо один клієнт має два ContactID у SendPulse (тестовий + реальний) → два окремі чати.
**Рішення:** Додано другий рівень пошуку по `partner_id + service` (якщо партнер відомий). При знаходженні — оновлюємо `sendpulse_contact_id` на актуальний.

#### 4. Помилка завантаження модуля: `External ID not found`
**Причина:** Кнопка "Ідентифікувати клієнта" у form view використовувала `%(module.xml_id)d` синтаксис — wizard views завантажуються після connect views.
**Рішення:** Замінено на `type="object" name="action_identify_partner"`. Метод `action_identify_partner` виправлено — тепер відкриває `sendpulse.identify.wizard`.

#### 5. Deprecated `attrs=` у wizard view
**Причина:** Odoo 17 більше не підтримує `attrs=` для умовних атрибутів.
**Рішення:** Атрибут видалено.

#### 6. Server action "Sync Discuss каналів"
**Додано:** Bulk-action у list view (тільки для admin):
- Для розмов без каналу → створює `discuss.channel`
- Для існуючих каналів → додає всіх поточних операторів як учасників

#### 7. Іконка модуля
**Проблема:** Головний екран використовує `ir.ui.menu.web_icon`, а не `ir.module.module.icon`.
**Рішення:** Додано `web_icon="odoo_chatwoot_connector,static/description/icon.png"` до root menuitem. Іконка — `sendpulse_logo.png` (темне коло з символом пульсу).

#### 8. Назва модуля у польськомовному UI
**Проблема:** `ir_module_module.shortdesc` для `pl_PL` містив стару назву "Odoo Chatwoot Connector".
**Рішення:** Оновлено напряму у БД через SQL.

### Бекап бази
Перед видаленням HelpCrunch створено бекап:
```
/opt/campscout/backups/campscout_before_helpcrunch_remove_20260326_181048.sql.gz
Розмір: 161 MB
```

---

## 17. ТЗ — Завдання на наступну сесію

### ПРІОРИТЕТ 1 — Критичне

#### 1.1 Видалення модуля HelpCrunch
**Статус:** Бекап зроблено, очікує підтвердження.
**Дії:**
1. Деінсталювати через Odoo (Settings → Apps → Helpcrunch → Uninstall)
2. Видалити файли з сервера: `rm -rf /opt/campscout/addons/helpcrunch`
3. Перевірити що поле "Helpcrunch Connect" зникло з `discuss.channel` form
4. Перевірити що меню HelpCrunch зникло з головного екрану

**Ризики:** 70 записів `helpcrunch_connect` будуть видалені разом з модулем. Бекап є.

#### 1.2 Тест webhook від реального клієнта end-to-end
**Мета:** Переконатись що повний цикл працює:
1. Клієнт пише у Telegram → webhook → `sendpulse.connect` створюється → `discuss.channel` з'являється у Discuss
2. Оператор відповідає у Discuss → повідомлення доходить до клієнта у Telegram
3. Ідентифікація клієнта через wizard → партнер прив'язаний → повідомлення у картці партнера

#### 1.3 Призначити користувачів до груп SendPulse
**Мета:** Щоб нові чати автоматично з'являлись у Discuss для потрібних операторів.
**Дії:** Settings → Users → [оператор] → Access Rights → SendPulse Odo: Officer / Administrator

---

### ПРІОРИТЕТ 2 — Важливе

#### 2.1 Кешування OAuth токена
**Проблема:** Токен запитується при **кожній** відправці повідомлення (окремий HTTP запит до SendPulse).
**Рішення:** Кешувати токен в `ir.config_parameter` з expire time (3600 сек).
```python
# В _get_access_token():
ICP = self.env['ir.config_parameter'].sudo()
cached_token = ICP.get_param('odoo_chatwoot_connector.oauth_token')
cached_expire = ICP.get_param('odoo_chatwoot_connector.oauth_token_expire')
if cached_token and cached_expire and datetime.now().timestamp() < float(cached_expire):
    return cached_token
# ... інакше запитуємо новий
```

#### 2.2 Валідація webhook token
**Проблема:** Поле `sendpulse_webhook_token` зберігається, але **не використовується** для перевірки запитів.
**Рішення:** У `controllers/main.py` перевіряти заголовок `X-SendPulse-Token` або параметр запиту.

#### 2.3 Попередження при відповіді після 24 годин (Meta канали)
**Проблема:** Instagram/Facebook/Messenger блокують відповіді після 24 год. Оператор не бачить помилки.
**Рішення:** У `send_message_to_sendpulse()` перевіряти `last_message_date`. Якщо > 24 год і сервіс Meta → показувати `UserError` або `_logger.warning`.

#### 2.4 Вхідні вкладення від клієнта у Discuss
**Проблема:** Якщо клієнт надіслав фото/файл — `attachment_url` зберігається в `sendpulse.message`, але в Discuss показується лише як текстове посилання.
**Рішення:** При постингу у `discuss.channel` для повідомлень з `attachment_url` — вставляти HTML `<img>` або `<a>` з посиланням.

---

### ПРІОРИТЕТ 3 — Покращення UX

#### 3.1 Автозакриття застарілих розмов
Додати cron який архівує розмови без активності > 30 днів (додати до `clean_data_cron.xml`).

#### 3.2 Кнопка "Відповісти у SendPulse" у Discuss
Замість стандартного повідомлення — додати окрему кнопку/shortcut у discuss.channel для відправки у SendPulse (щоб оператор чітко бачив що відповідь іде в месенджер).

#### 3.3 Dashboard / Звіти
Простий graph view у `sendpulse.connect`: кількість чатів по каналах, по статусах, по операторах — за тиждень/місяць.

#### 3.4 Підтримка шаблонів відповідей
Інтеграція з `mail.template` або простий список швидких відповідей для операторів.

---

### Інфраструктура

| Задача | Статус |
|--------|--------|
| Бекап БД перед змінами | ✅ Зроблено (161 MB) |
| Git репозиторій | ✅ `main` branch актуальний |
| Деплой на сервер | ✅ `/opt/campscout/custom-addons/odoo_chatwoot_connector/` |
| Призначення операторів до груп | ⏳ Потрібно зробити вручну |
| Видалення HelpCrunch | ⏳ Очікує підтвердження |
| End-to-end тест | ⏳ Потрібно провести |

---

*Лог сесії та ТЗ додані: 2026-03-26.*
*Для питань та пропозицій: https://github.com/VladSh77/odoo-chatwoot-connector*
