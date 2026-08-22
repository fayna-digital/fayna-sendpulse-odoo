# Odoo 17 Інтеграція SendPulse — AI + Lead Magnet + Multi-Page FB/IG

![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20Community-purple)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Meta Graph](https://img.shields.io/badge/Meta%20Graph-v25.0-red)
![License](https://img.shields.io/badge/License-OPL--1-green.svg)
![Status](https://img.shields.io/badge/Status-Production-brightgreen)

**Розроблено [Fayna Digital](https://www.fayna.agency) для CampScout**
**Автор: Volodymyr Shevchenko**

---

Двосторонній міст **SendPulse ↔ Odoo Discuss** з AI-асистентом для операторів, lead magnet flow (PDF-каталог + SMS-купон), обізнаністю про наявність місць на заходах, drip-кампаніями, A/B-тестуванням шаблонів, автоперекладом та підтримкою декількох Facebook/Instagram-сторінок з LLM-класифікацією коментарів. **Авто-створення crm.lead** з чату (коли клієнт відповів) — лід падає в лійку Sales **без відповідального** (пул + claim), щоб двоє менеджерів не вели одного клієнта. Див. [docs/TZ_F4_ENABLE_LEAD.md](docs/TZ_F4_ENABLE_LEAD.md).

Еталонне розгортання: [CampScout](https://campscout.eu) — дитячі літні табори в Польщі.

---

## Можливості

- **Єдина скринька** — Telegram / Instagram / Facebook / Messenger / Viber / WhatsApp / LiveChat / TikTok — усе надходить в один `mail.channel` у Odoo Discuss
- **Декілька FB/IG-сторінок** — 11 Facebook-сторінок + 7 Instagram через токени System User; пройдено Meta App Review 2026-04-20
- **AI-асистент для оператора** — Claude Haiku 4.5 генерує відповіді у бічній панелі Discuss (OWL-компонент)
- **Lead magnet flow** — email → брендований PDF-каталог; телефон → SMS-купон з пулу `loyalty.program`
- **Наявність місць на заходах** — AI отримує реальну кількість `seats_available` для кожного табору → чесний FOMO або запасне повідомлення
- **Drip-кампанії** — нагадування через 6 год / 24 год з перевіркою cooldown та згоди
- **A/B публічні шаблони** — epsilon-greedy вибір з відстеженням конверсій по варіантах
- **Автопереклад** — UA ↔ PL через Claude, прямо в Discuss
- **FAQ RAG автовідповідь** — Claude з порогом впевненості автоматично відправляє безпечні відповіді
- **Класифікатор коментарів** — 8 категорій (питання, скарга, спам, похвала тощо) з LLM + маршрутизація алертів у Telegram
- **RODO/GDPR** — кожна подія згоди фіксується у `sendpulse.privacy.consent.log` (журнал append-only з захистом від зміни)

---

## Архітектура

```
sendpulse-odoo/
├── models/
│   ├── sendpulse_connect.py              # Основна модель — одна розмова на запис (~4000 рядків)
│   ├── sendpulse_message.py              # Журнал повідомлень
│   ├── sendpulse_facebook_page.py        # Стан для декількох FB/IG-сторінок
│   ├── sendpulse_faq_entry.py            # База знань FAQ для RAG
│   ├── sendpulse_public_template.py      # A/B публічні шаблони + конверсії
│   ├── sendpulse_identify_wizard.py      # Майстер ручного зв'язування з партнером
│   ├── sendpulse_privacy_consent_log.py  # Журнал RODO-згод (append-only)
│   ├── res_config_settings.py            # Налаштування модуля
│   ├── res_partner.py                    # Розширення партнера (UTM, історія каналів)
│   └── mail_channel.py                   # Розширення каналу Discuss
├── controllers/
│   └── main.py                           # SendPulse webhook + Meta Graph callbacks
├── views/
│   ├── sendpulse_connect_views.xml       # Kanban, форма, список, бічна панель Discuss
│   └── ...
├── data/
│   ├── sendpulse_data.xml                # Меню + дії
│   ├── sendpulse_faq_seed.xml            # Початкові FAQ-записи
│   ├── mail_template_lead_magnet.xml     # Брендований email для lead magnet
│   └── clean_data_cron.xml               # Розклад автоочищення
├── static/src/
│   ├── components/                       # OWL-компоненти (AI-панель, інформаційна панель)
│   └── scss/
└── docs/
    ├── INDEX.md                          # Навігація по документації
    ├── ARCHITECTURE.md
    ├── CONFIGURATION.md
    ├── DEPLOYMENT.md
    └── TZ_V2_AUTOMATION.md
```

---

## Технологічний стек

| Компонент | Технологія |
|-----------|-----------|
| ERP-фреймворк | Odoo 17.0 Community |
| Основні залежності | `mail`, `contacts`, `crm`, `web` |
| Провайдер месенджерів | SendPulse Chatbot API + webhooks |
| Соціальний граф | Meta Graph API v25.0 (через токени System User) |
| AI | Claude Haiku 4.5 (Anthropic API) |
| SMS | TurboSMS (через `kw_sms_api`) |
| Стратегія повторів | Exponential backoff, аудит-журнал через ir.logging |
| Race-safety | PostgreSQL advisory lock + partial unique index |
| Версія модуля | 17.0.1.15.13 |
| Ліцензія | OPL-1 (Odoo Proprietary) |

---

## Встановлення

### 1. Клонування в custom-addons

```bash
cd /opt/<client>/custom-addons
git clone https://github.com/fayna-digital/fayna-sendpulse-odoo.git odoo_chatwoot_connector
```

> **Примітка:** технічна назва директорії — `odoo_chatwoot_connector` (з історичних причин після перейменування репо). Технічна назва модуля Odoo залишається `odoo_chatwoot_connector` в маніфесті.

### 2. Встановлення модуля

```bash
docker exec <client>_web odoo -c /etc/odoo/odoo.conf -d <db> \
    -i odoo_chatwoot_connector --stop-after-init --no-http
```

Або через UI: **Застосунки → Оновити список застосунків → пошук `SendPulse` → Встановити**.

### 3. Перезапуск Odoo

```bash
docker restart <client>_web
```

---

## Налаштування

### Крок 1 — Облікові дані SendPulse

1. Увійдіть на [login.sendpulse.com](https://login.sendpulse.com) → **Налаштування → REST API**
2. Скопіюйте **ID** і **Secret**
3. В Odoo: **Налаштування → Технічне → Системні параметри** (потрібен режим розробника):

| Ключ | Значення |
|-----|-------|
| `sendpulse.api_id` | ваш SendPulse REST API ID |
| `sendpulse.api_secret` | ваш SendPulse REST API Secret |
| `sendpulse.webhook_secret` | випадковий рядок (спільний з налаштуванням webhook) |

### Крок 2 — URL webhook у SendPulse

В панелі SendPulse → **Chatbot → Налаштування → Webhook**:

- URL: `https://<your-odoo>.com/sendpulse/webhook`
- Події: `income_message`, `outcome_message`, `bot_comment` (якщо використовується FB)

### Крок 3 — Meta App для FB/IG (необов'язково)

Дивіться [docs/CONFIGURATION.md](docs/CONFIGURATION.md) для повного flow з Meta App Review та налаштуванням System User.

### Крок 4 — Облікові дані AI

| Ключ | Значення |
|-----|-------|
| `sendpulse.anthropic_api_key` | Anthropic API key для Claude |
| `sendpulse.claude_model` | `claude-haiku-4-5-20251001` (за замовчуванням) |

### Крок 5 — TurboSMS (для SMS-купонів)

Налаштуйте провайдера `kw_sms_api` з обліковими даними TurboSMS — див. `campscout-management/docs/DEPLOYMENT.md`.

---

## Використання

### Оператор отримує чат

1. Клієнт пише у будь-який підключений канал (наприклад, Telegram)
2. Webhook надходить на `/sendpulse/webhook`
3. Створюється `sendpulse.connect` (гілка), прив'язана до `mail.channel`
4. Оператор бачить повідомлення в Odoo Discuss з картою інформації про партнера
5. Оператор відповідає — міст надсилає через SendPulse API → назад у Telegram

### Запуск lead magnet

1. Відкрийте запис `sendpulse.connect` у бічній панелі
2. Натисніть **Надіслати PDF-каталог** → запитає email (або заповнить автоматично, якщо визначено)
3. Модуль:
   - Надсилає брендований PDF через AWS SES
   - Записує згоду в `sendpulse.privacy.consent.log` з `purpose='lead_magnet_email'`
   - Оновлює чат підтвердженням

### AI-відповіді

1. У режимі розробника в бічній панелі Discuss з'являється кнопка «Згенерувати AI-відповідь»
2. Claude Haiku отримує:
   - Останні 20 повідомлень розмови
   - RFM-сегмент партнера
   - Контекст наявності місць (FOMO-повідомлення, якщо < 30%)
   - Топ-3 записи FAQ RAG
3. Оператор переглядає, редагує, надсилає

Дивіться [docs/TZ_V2_AUTOMATION.md](docs/TZ_V2_AUTOMATION.md) для всіх автоматизованих flow.

---

## RODO / GDPR — Журнал згод

Кожен виклик `sendpulse.privacy.consent.log.record_consent()` створює append-only запис у `sendpulse.privacy.consent.log` — юридично захищений журнал з блокуванням зміни та видалення.

```python
# Внутрішній flow, автоматично:
self.env['sendpulse.privacy.consent.log'].record_consent(
    purpose='lead_magnet_email',
    channel='email',
    email=email,
    partner_id=partner.id,
    exact_response=user_text,
    source='sendpulse_chat',
)
```

Автоматизація через `base.automation`:
- Додавання до `mail.blacklist` → автоматичний запис відкликання (withdrawal) у журнал RODO

---

## Webhook Flow (технічно)

```
1. SendPulse отримує повідомлення від каналу клієнта (Telegram/IG/FB/…)
2. POST https://<odoo>/sendpulse/webhook з підписаним payload
3. sendpulse/controllers/main.py:
   a. Перевірка підпису (HMAC-SHA256 з webhook_secret)
   b. Дедублікація за (service + sendpulse_contact_id + timestamp)
   c. Advisory lock на (contact_id, service) для захисту від race condition
4. Створення або оновлення запису sendpulse.connect (гілка)
5. Створення запису sendpulse.message (журнал)
6. Дублювання в mail.channel (Discuss):
   a. Новий контакт → створення каналу
   b. Публікація повідомлення через mail.channel._message_post_feedback()
7. Запуск AI-задачі за умов (FAQ-збіг, розклад drip)
8. Повернення 200 OK
```

---

## Meta Graph API Flow (технічно)

```
1. Клієнт коментує публікацію на Facebook Page
2. Спрацьовує webhook підписки на сторінку → /sendpulse/webhook/meta
3. Отримання page_access_token з sendpulse.facebook.page (11 сторінок в роботі)
4. Отримання повного тексту коментаря через Graph API v25.0
5. Класифікація через LLM (8 категорій: питання/спам/похвала/…)
6. Маршрутизація:
   - Категорія 'question' → автовідповідь через Graph API send_message
   - Категорія 'spam' → приховати коментар
   - Категорія 'complaint' → Telegram-алерт черговому менеджеру
7. Запис у ir.logging (аудит)
```

---

## Локальна розробка

```bash
git clone https://github.com/fayna-digital/fayna-sendpulse-odoo.git
cd fayna-sendpulse-odoo

# Запуск тимчасового Odoo з підключеним модулем:
docker run -d --name test_odoo -v $(pwd)/..:/mnt/custom-addons \
    -p 8069:8069 odoo:17

# Симуляція SendPulse webhook:
curl -X POST http://localhost:8069/sendpulse/webhook \
    -H "Content-Type: application/json" \
    -d '{"service": "telegram", "contact": {...}, "message": {...}}'
```

Дивіться [docs/CONFIGURATION.md](docs/CONFIGURATION.md) для налаштування секретів розробки.

---

## Усунення несправностей

| Помилка | Причина | Виправлення |
|-------|-------|-----|
| `ValueError: Invalid field 'sent_at' on model 'sendpulse.message'` | Стара помилка — поле `date`, не `sent_at` | Виправлено у v17.0.13.1; якщо бачите — оновіть модуль |
| Перевірка підпису не вдається | Невідповідність webhook secret | Синхронізуйте `sendpulse.webhook_secret` між Odoo та панеллю SendPulse |
| Дублікати `sendpulse.connect` для того ж контакту | Відсутній advisory lock / partial unique index | v17.0.10.x додав `_sendpulse_dedup_idx`, переконайтесь що оновлення пройшло |
| Помилка Meta Graph 401 | Токен System User закінчився або токен сторінки відкликано | Щотижневий cron перевіряє токени; повторно авторизуйтесь у Meta Business Settings |
| AI-панель не рендериться в Discuss | Кешований OWL asset bundle | Жорстке оновлення (Ctrl+Shift+R); якщо не допомагає — очистіть кеш через `odoo shell` → `self.env['ir.qweb']._clear_cache()` |
| Lead magnet email не надсилається | AWS SES sandbox (лише перевірені одержувачі) | Запросіть виробничий доступ SES; або додайте одержувачів у whitelist |

---

## Доступ операторів

Стандартна модель доступу Odoo Discuss — не потрібна окрема група модуля. Усі користувачі з `mail.group_user` можуть:

- Переглядати вхідні підключених каналів
- Відповідати в гілках
- Переглядати бічну панель партнера

**Адмін модуля** (`group_omnichannel_admin` у `sendpulse-odoo`) також:

- Налаштовувати облікові дані SendPulse
- Керувати FB/IG-сторінками
- Редагувати FAQ-записи
- Переглядати журнали LLM

---

## Екосистема модулів

Цей модуль є частиною стеку Fayna Digital Odoo:

| Суміжний модуль | Зв'язок |
|----------------|--------------|
| [fayna-omnichannel-bridge](https://github.com/fayna-digital/fayna-omnichannel-bridge) | Абстрактний агрегатор месенджерів — sendpulse-odoo є одним з адаптерів |
| [fayna-zadarma-odoo](https://github.com/fayna-digital/fayna-zadarma-odoo) | Голосовий канал (доповнює месенджери) |
| [campscout-management](https://github.com/VladSh77/campscout-management) | Вертикальний шар CampScout — використовує sendpulse-odoo для всіх chat flow |

Документація архітектури: [fayna-digital-docs](https://github.com/VladSh77/fayna-digital-docs) (приватне).

---

## Ліцензія

OPL-1 (Odoo Proprietary License v1.0) — дивіться [LICENSE](LICENSE)

---

*Розроблено [Fayna Digital](https://www.fayna.agency) · Volodymyr Shevchenko*
