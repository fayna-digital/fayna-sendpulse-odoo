# CHANGELOG — odoo-chatwoot-connector (SendPulse Connector)

Формат: `## [date] — YYYY-MM-DD`

---

## [2026-04-20] — v17.0.3.7.0

### Multi-page FB/IG — повний refactor

**Що змінилось у flow обробки коментарів:**
- `_process_comment_event` тепер резолвить `sendpulse.facebook.page` запис за `page_id` з webhook (метод `find_by_page_id`) — на початку обробки, ще до self-loop guard.
- На `sendpulse.connect` додано поле **`sp_page_id`** (indexed Char) — зберігає Page ID з webhook, щоб наступні операції знали з якої Сторінки відповідати.
- **Self-loop guard** тепер збирає власні ID з усіх активних Page-ів (не тільки legacy `ig_user_id`) — захист від циклу для всіх 11 сторінок.
- **Per-page URL overrides**: шаблони публічних/приватних відповідей підставляють `page.landing_url / tg_url / yt_url` якщо заданий, інакше глобальний ICP.

**API-caller-и**: `_hide_comment`, `_send_comment_public_reply`, `_send_comment_private_reply` тепер приймають `page=None`. Через `_get_fb_page_token(page=page)` токен резолвиться з пріоритетом:
1. `page.access_token` (якщо передано)
2. Page за `self.sp_page_id` (для повторних операцій у тій самій розмові)
3. Default Page (`is_default=True`)
4. Legacy `ir.config_parameter.fb_page_access_token`

Для IG private_reply — `ig_user_id` береться з `page.ig_business_id` замість глобального.

**Cron токен-перевірки**: `cron_check_fb_token_expiry` тепер ітерує всі активні `sendpulse.facebook.page` записи + окремо legacy токен. Для кожного запускається `_check_single_fb_token(token, label)` — записує `token_status` і `last_checked_at` безпосередньо на Page record. Telegram-алерт з міткою сторінки (`[CampScout]`, `[Raid Camp]` тощо). Дублі уникаються — якщо legacy токен = токен якоїсь Page, legacy просто мітиться як `valid (mirrored by Page "...")`.

### Settings UI — секція Multi-page

Додано секцію у Settings form:
- `fb_pages_count` (readonly) — скільки активних Page-записів
- `fb_sync_user_token` (password input, не зберігається) — User Access Token з Graph API Explorer
- Кнопка **"Синхронізувати з Meta /me/accounts"** → викликає `sync_from_meta(user_token)` → створює/оновлює записи Pages з їхніми безстроковими токенами і IG Business ID
- Linkи на Graph API Explorer + довідка про обмеження

### Sendpulse Pages menu

Доступне через Налаштування → Технічне → SendPulse → Facebook Pages (action `action_sendpulse_facebook_page`). Tree + form, кнопка "Перевірити токен" у form-view.

### Backward compatibility

Legacy `ir.config_parameter.fb_page_access_token` + `ig_user_id` продовжують працювати як fallback якщо в `sendpulse.facebook.page` немає записів АБО webhook не приніс `page_id`. Існуючі розмови продовжують відповідати через CampScout Page Token — нічого не ламається.

### Пам'ятай

Коли новий User Token сгенерується → у Settings треба натиснути "Синхронізувати з Meta" — це створить 11 Page-записів (CampScout + 10 інших) з їхніми безстроковими Page Tokens. Модуль автоматично маршрутизує відповіді на правильну сторінку за `page_id` з webhook.

---

## [2026-04-20] — v17.0.3.6.2

### Settings UI

Додано поля у форму Налаштування → SendPulse Odo для фіч, які з'явилися у попередніх 3.2.x–3.6.1 релізах але залишилися без UI (конфігурувалися лише через `ir.config_parameter`):

- **Instagram**: `ig_user_id` (для private_reply на IG-коментарі)
- **Facebook App**: `fb_app_id`, `fb_app_secret` (для /debug_token експіри-треку), readonly `fb_token_status`, `fb_token_last_check`
- **LLM-класифікатор**: `llm_classifier_enabled`, `anthropic_api_key`, `llm_model`, `sp_comment_hide_spam_enabled`
- **Telegram-алерти**: `telegram_alerts_enabled`, `telegram_bot_token`, `telegram_chat_id`

Усі секретні поля з `password="True"`. Залежні поля ховаються через `invisible="not <toggle>"` — якщо LLM/Telegram вимкнені, API-ключі не показуються взагалі.

### Архітектура — conflict resolution

Під час інтеграції попередніх стеш-змін (v17.0.3.2.x–3.6.1) знято комміт [`cbd428b`](https://github.com/faynadigital/sendpulse-odoo/commit/cbd428b) (`_ai_classify_comment` через Gemini 2.5 Flash, OpenAI-compatible API) — замінено на `_classify_comment` через Anthropic Claude Haiku з 8 категоріями. Причина: Anthropic-версія повертає не binary `reply/skip`, а структуроване `thanks/spam/complaint/question_*` — це дозволяє різну маршрутизацію (thanks не потребує відповіді, spam ховається, complaint ескалюється у Telegram).

Старі config-ключі `ai_filter_enabled`, `ai_api_key`, `ai_base_url`, `ai_model` більше не використовуються (залишаються у БД, але ігноруються).

---

## [2026-04-19] — v17.0.3.6.1

### Надійність

**Audit log для FB/IG Graph API викликів (#12 з roadmap)**

Новий метод `_log_fb_audit(label, url, payload, status, response, attempts)` пише у `ir.logging` з `name='odoo_chatwoot_connector.fb_api'`. Інтегровано в `_fb_post_with_retry`: кожен виклик (успіх, 4xx без retry, всі retries exhausted, exception) створює запис з:
- URL і тілом запиту (з редагованим `access_token`)
- HTTP-кодом і тілом відповіді (перші 500 символів)
- Кількістю спроб

**Що це дає**:
- Пошук у Technical → Logging за фільтром `name=odoo_chatwoot_connector.fb_api` показує всі API-виклики
- Коли щось ламається — одразу видно точний request+response замість здогадок
- Статистика (скільки спам-приховувань на день, скільки private_replies впало з 24h-вікном)
- Доказ для Meta App Review аудиту — що саме робив токен

Безпечно: записи аудиту не ламають основний флоу (try/except навколо write).

---

## [2026-04-19] — v17.0.3.6.0

### Нові можливості

**Метрики воронки конверсії (#9 з roadmap)**

Нові поля на `sendpulse.connect`:
- `sp_funnel_stage` (Selection, index) — стадія воронки:
  - `comment_only` — коментар під постом, ніякої відповіді
  - `private_sent` — автовідповідь надіслана в приват
  - `customer_replied` — клієнт відписав у приват (перетворення!)
  - `operator_engaged` — оператор підключився до розмови
  - `lead_created` — створено CRM-лід
  - `closed_won` — конверсія в замовлення
  - `closed_lost` — втрата
- `sp_first_inbound_at` — дата першого повідомлення клієнта
- `sp_first_reply_at` — дата першої відповіді оператора
- `sp_first_reply_time_sec` (computed, stored) — швидкість реакції в секундах
- `sp_lead_id` (M2O crm.lead) — зв'язок з лідом

**Переходи стадій (автоматично)**:
- Створення коментаря → `comment_only`
- Успішний `private_reply` → `private_sent`
- Inbound message від клієнта → `customer_replied` + `sp_first_inbound_at`
- Успішний `send_message_to_sendpulse` (оператор написав) → `operator_engaged` + `sp_first_reply_at`

Подальші стадії (`lead_created`, `closed_won/lost`) — поки ручні або через майбутню інтеграцію з CRM.

Користь: у list view `sendpulse.connect` з фільтром по `sp_funnel_stage` керівник бачить воронку: скільки коментарів → скільки приватних → скільки відповіли → скільки в обробці → конверсії. `sp_first_reply_time_sec` показує SLA операторів.

---

## [2026-04-19] — v17.0.3.5.0

### Нові можливості

**Messenger 24-годинне вікно — tracking + алерт (#8 з roadmap)**

Meta дозволяє Page писати клієнту в Messenger/IG Direct лише 24 години після його останньої активності (повідомлення, реакції, коментаря). Після — лише з `MESSAGE_TAG` або `HUMAN_AGENT` label. Раніше оператори не знали коли вікно закривається — просто не могли надіслати повідомлення.

**Зміни**:
- Нові поля на `sendpulse.connect`: `sp_messenger_window_expires_at`, `sp_window_alert_sent`
- Після успішного `private_reply` → вікно = `now + 24h`, `alert_sent = False`
- При inbound message → вікно продовжується на 24h, alert-прапорець скидається
- Новий cron `cron_check_messenger_windows()` кожні 30 хвилин:
  - Шукає розмови де вікно закривається у найближчі 2 години
  - Алерт у Telegram (silent): *"⏳ Вікно 24h скоро закриється — залишилось X хв"*
  - Нотатка у відповідний Discuss-канал
  - Позначає `alert_sent=True` щоб не дублювати

Причина: втрачали клієнтів тихо — оператор хотів уточнити/нагадати через день, не міг. Тепер є ранній сигнал за 2 години щоб прийняти рішення.

---

## [2026-04-19] — v17.0.3.4.1

### Покращення

**Ротація шаблонів публічної відповіді — per-post (#7 з roadmap)**

Було: `count = search_count([('sp_is_comment', '=', True)])` — глобальний лічильник усіх comment-розмов. Під вірусним постом з 20+ коментарями кожні 5 людей бачили однаковий шаблон, що робило відповіді бот-подібними.

Стало: лічильник обмежений до `sp_post_id` + `sp_replied_public=True`. Під одним постом гарантується унікальність кожного з 5 шаблонів, потім цикл починається заново — але природно, бо 6-й коментатор і 1-й не бачать один одного у стрічці коментарів.

Fallback на глобальний count якщо `post_id` пустий (старі записи без post_id).

---

## [2026-04-19] — v17.0.3.4.0

### Нові можливості

**Telegram-алерти менеджерам (ескалація)**

Новий метод `_notify_telegram(text, silent)` — HTTP POST на `api.telegram.org/bot{token}/sendMessage` з HTML parse mode. Інтегровано у 4 сценарії:

- 🚨 **Скарга** (LLM `category=complaint`) — гучне сповіщення з іменем клієнта, текстом, посиланням на пост
- 🚫 **Спам приховано** (після `_hide_comment`) — тихе сповіщення (`disable_notification=True`), щоб не будити менеджерів
- ⚠️ **FB Token недійсний** — критичний алерт (автовідповіді перестали працювати)
- ⚠️ **FB Token expires_soon** (<7 днів, з `cron_check_fb_token_expiry`) — попередження щоб встигнути регенерувати

Нові поля в Settings:
- `telegram_alerts_enabled` (checkbox, default OFF)
- `telegram_bot_token` (write-only, як API keys)
- `telegram_chat_id` (Chat ID групи — від'ємне число для груп)

Якщо `telegram_alerts_enabled=False` або токен не налаштовано — метод тихо повертає `False`, нічого не ламає.

---

## [2026-04-19] — v17.0.3.3.1

### Нові можливості

**Автоматичне приховування спам-коментарів (#6 з roadmap)**

Новий метод `_hide_comment(comment_id, service)`:
- FB: `POST /v25.0/{comment_id}` body `{is_hidden: true}`
- IG: `POST /v25.0/{comment_id}` body `{hide: true}`

**Логіка**: якщо LLM-класифікатор (#5) повернув `category=spam` + увімкнено `sp_comment_hide_spam_enabled` (default `True`) → коментар приховується. Хостить через retry-wrapper `_fb_post_with_retry`, тому transient errors не критичні.

Причина: без автоприховування операторам доводилось вручну модерувати спам під кожним рекламним постом. Тепер LLM → hide → тиша.

Нове поле в Settings: `sp_comment_hide_spam_enabled` (checkbox, default ON).

---

## [2026-04-19] — v17.0.3.3.0

### Нові можливості

**LLM-класифікатор коментарів (#5 з roadmap)**

Автоматична класифікація коментарів FB/IG через Anthropic Claude у 8 категорій:
`question_price`, `question_dates`, `question_age`, `question_general`, `thanks`, `complaint`, `spam`, `other`.

**Маршрутизація за категорією**:
- `thanks`, `spam` → автовідповідь НЕ надсилається (публічний шаблон на подяку виглядає як бот)
- `complaint` → автовідповідь НЕ надсилається, оператор отримує нотатку `🚨 СКАРГА` для ручної обробки
- `question_*` / `other` → поточна логіка (public + private)

**Нові поля**:
- `sendpulse.connect.sp_comment_category` — selection з категорією
- Settings: `llm_classifier_enabled`, `anthropic_api_key`, `llm_model` (default `claude-haiku-4-5`)
- Нотатка оператору тепер містить мітку категорії

**Вартість**: Claude Haiku ~$0.80/M tok input → ~$0.20/1000 коментарів. Якщо вимкнено → `other` (поточна поведінка, без API-викликів).

---

## [2026-04-19] — v17.0.3.2.2

### Безпека

**Self-loop guard для коментарів FB/IG (#4 з roadmap)**

У `_process_comment_event` додано перевірку перед публічною/приватною відповіддю: якщо `from.id` коментаря збігається з власним `page_id` (з payload) або `ig_user_id` (з config) — коментар пропускається з логом.

Причина: без захисту наша публічна відповідь генерує новий коментар з новим `comment_id` → FB/IG надсилає webhook на той коментар → Odoo "бачить новий коментар" → відповідає → нескінченний цикл. Dedup по `sp_comment_id` не ловив це (новий коментар = новий ID).

---

## [2026-04-19] — v17.0.3.2.1

### Надійність

**Retry з exponential backoff для FB Graph API (#2 з roadmap)**

Новий хелпер `_fb_post_with_retry(url, payload, label)` — 3 спроби з затримкою 1s/3s/9s. Rozфактор: обидва колбеки (`_send_comment_public_reply`, `_send_comment_private_reply`) тепер ідуть через нього.

Політика retry:
- **Повторюємо**: мережеві помилки (ConnectionError, Timeout), HTTP 5xx, HTTP 429 (rate limited)
- **Не повторюємо**: HTTP 4xx крім 429 (bad request, invalid token, blocked user — permanent errors, retry марний)

Причина: до цього фіксу network glitch або тимчасовий 5xx від Meta = втрата коментаря (оператор бачив помилку, клієнт — нічого). Тепер прозоре відновлення з логами по кожній спробі.

---

## [2026-04-18] — v17.0.3.2.0

### Нові можливості

**Автоперевірка терміну дії Facebook Page Access Token (#1 з roadmap)**

Новий cron `SendPulse Odo: Перевірка FB Page Access Token` (раз на 7 днів):
- `GET /v25.0/me` → перевіряє валідність токена
- `GET /v25.0/debug_token` → точний `expires_at` (якщо є `fb_app_id` + `fb_app_secret`)
- Статус зберігається у `ir.config_parameter`: `fb_token_status`, `fb_token_last_check`, `fb_token_expires_at`
- Якщо залишилось <7 днів або токен невалідний → `_logger.error` + статус `expires_soon: Nd` / `invalid: <reason>`

Нові поля в Settings:
- `fb_app_id`, `fb_app_secret` — для debug_token (без них показуємо лише валідність, без дат)
- `fb_token_status` (readonly) — поточний стан
- `fb_token_last_check` (readonly) — дата останньої перевірки

Причина: System User Page Token може стихати (60 днів за замовчуванням). Без моніторингу — тихий збій автовідповідей.

---

## [2026-04-18] — v17.0.3.1.1

### Оновлення

**Facebook Graph API v19.0 → v25.0**

Усі 3 виклики FB/IG Graph API підняті з v19.0 (реліз Jan 2024) до v25.0:
- `_send_comment_public_reply` → POST `/v25.0/{comment_id}/comments` (або `/replies` для IG)
- `_send_comment_private_reply` (FB) → POST `/v25.0/{comment_id}/private_replies`
- `_send_comment_private_reply` (IG) → POST `/v25.0/{ig_user_id}/messages`

Причина: v19.0 біля двох років → зона deprecation (Meta знімає версії після 2 років). v25.0 — поточна стабільна, покриває EU DMA compliance + актуальні error codes + нові поля conversations API.

---

## [2026-04-12] — v17.0.3.1.0

### Виправлення

**1. Рекурсія `message_post` в блоках помилок** _(commit f6fe0d4)_

`message_post` у трьох `except`-блоках `send_message_to_sendpulse` не мав контексту `sendpulse_incoming=True` → кожна помилка API запускала повторну спробу надіслати повідомлення → нескінченна петля. Додано `with_context(sendpulse_incoming=True)` до всіх трьох `message_post`.

**2. Збереження історії — заборонено архівування `discuss.channel`** _(commit 5ef5b3a)_

`action_close` і `_close_channel` виставляли `active=False` на `discuss.channel` → канал зникав із Discuss, frontend повертав 404, вся переписка ставала недоступною. Виправлено: `action_close` тепер лише виставляє `stage='close'`, `_close_channel` — порожній метод. Відновлено 85 архівованих каналів через SQL (`active = true`).

**3. Статус "Нове повідомлення" залишався після відповіді оператора** _(commit cdaf029)_

`stage: new_message → in_progress` відбувалося лише через кнопку "Відкрити чат" у списку розмов (`action_open`). Якщо менеджер відповідав напряму в Discuss — статус назавжди залишався `new_message`. Додано знімання позначки в `mail_channel.py` після відправки повідомлення через API.

**4. 422-handler: хибне повідомлення "Meta 24h вікно"** _(commit 7dca1eb)_

Усі 422-помилки отримували однакову підказку "вікно відповіді закрите (Meta 24h)". SendPulse повертає HTTP 422 з `error_code: 403` у тілі для різних причин (наприклад, "Forbidden: bot was blocked by the user" у Telegram). Виправлено: хендлер парсить JSON-тіло, визначає `error_code` і показує точну причину — "клієнт заблокував бота" або "вікно 24h Meta" для Facebook/Instagram.

---

## [2026-04-11] — v17.0.3.0.0

### Нові можливості

**Автовідповідь на коментарі Facebook / Instagram (Comment Autoreply)**

Нова функціональність для автоматичної обробки коментарів під постами FB/IG через Facebook Graph API.

**Як працює:**
1. SendPulse надсилає `incoming_message` з `item=comment` у webhook
2. Система розпізнає коментар і направляє до нового методу `_process_comment_event()`
3. Публікується публічна відповідь під коментарем (Graph API `/{comment_id}/comments`)
4. Надсилається приватне повідомлення клієнту (Graph API `/{comment_id}/private_replies`)
5. Оператор отримує нотатку в Discuss з текстом коментаря, URL поста і статусом відправки

**Дедуплікація (маркетингова логіка):**
- Публічна відповідь — **завжди** (видна всій аудиторії поста, підвищує охоплення)
- Приватне повідомлення — **тільки перший раз** для кожного контакту (не спамимо)
- Захист від дублювання одного comment_id (SendPulse може надіслати двічі)

**5 ротаційних шаблонів** публічної відповіді з підстановкою:
- `{landing_url}` → лендінг https://lato2026.campscout.eu
- `{tg_url}` → ТГ-канал https://t.me/campscouting (+ знижка -5%)

**Нові поля `sendpulse.connect`:**
- `sp_is_comment`, `sp_comment_id`, `sp_comment_text`, `sp_post_id`, `sp_post_url`
- `sp_replied_public`, `sp_replied_private`

**Нові поля Налаштувань (Налаштування → SendPulse Odo → Відповіді на коментарі):**
- Перемикачі: автовідповідь, публічна, приватна
- `Facebook Page Access Token` (password, зберігається в ir.config_parameter)
- `sp_comment_landing_url`, `sp_comment_tg_url`, `sp_comment_yt_url`
- `sp_comment_private_text` (кастомний текст приватного повідомлення)

**Нові методи `sendpulse.connect`:**
- `_process_comment_event()` — головна логіка
- `_send_comment_public_reply()` — Graph API публічна відповідь
- `_send_comment_private_reply()` — Graph API private_reply
- `_get_fb_page_token()` — читає токен з ir.config_parameter
- `_parse_fb_error()` — парсить помилки Graph API
- `_notify_operator_comment()` — нотатка OdooBot у Discuss

### Виправлення

**Сповіщення оператора при помилках доставки (400 / Exception)**
- Код 400 `contact.errors.not_active` → повідомлення ❌ в Discuss з поясненням
- Загальний Exception handler → повідомлення ❌ в Discuss з текстом помилки
- (Раніше: лише логувалися як ERROR без видимого сигналу оператору)

---

## [2026-04-11] — КРИТИЧНИЙ ІНЦИДЕНТ (AI: витік паролів сервера в UI розмови)

<div style="color:#b00020; border-left:4px solid #b00020; padding-left:12px;">

**Клас:** критична помилка безпеки — три окремі витоки серверних паролів у контекст AI-сесії.

**Інцидент 1:** `docker inspect` → plaintext env усіх контейнерів у консоль.
**Інцидент 2:** `cat .env` → повний вміст `.env` у консоль.
**Інцидент 3:** нові паролі (ротація 1+2) виведені у текст відповіді та `IN`-параметр bash-команди.

**Ремедіація:** Ротація 3 — паролі згенеровані та застосовані повністю на сервері через `bash -s` heredoc без витоку значень. PostgreSQL `ALTER USER` виконано. Контейнери перезапущені.

**Правило:** ніколи не використовувати `docker inspect`, `cat .env`, або генерувати паролі локально. Лише `ssh server 'bash -s' << SCRIPT ... SCRIPT`.

**Документація:** `docs/CRITICAL_INCIDENT_AI_PASSWORD_EXPOSURE_2026-04-11.md`

</div>

---

## [2026-04-11] — КРИТИЧНИЙ ІНЦИДЕНТ (AI: зміни коду без ТЗ / порушення `repo-deploy-server-gate`)

<div style="color:#b00020; border-left:4px solid #b00020; padding-left:12px;">

**Клас:** критична **процесна** помилка сесії Cursor — зміна **`sendpulse-odoo/models/sendpulse_connect.py`** (евристика URL медіа, логіка завантаження) **без** письмового ТЗ, **без** явної вказівки користувача на зміну цього модуля та **без** тестів у репо; інтерпретація запиту **«тестуй»** як дозвіл на патч.

**Наслідки для git:** зміни **не пушились** у remote; після зауваження користувача робоче дерево **відновлено** (`git checkout -- models/sendpulse_connect.py`).

**Документація:** **`docs/CRITICAL_INCIDENT_AI_UNAUTHORIZED_EDIT_SENDPULSE_CONNECT_2026-04-11.md`**, `docs/CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md` **§8**, `DevJournal/sessions/LOG.md` (розділ **2026-04-11**).

</div>

---

## [2026-04-11] — КРИТИЧНИЙ ІНЦИДЕНТ (AI: порушення меж модулів) — **відкат коду**

<div style="color:#b00020; border-left:4px solid #b00020; padding-left:12px;">

**Клас:** критична помилка роботи агента — **невиконання вимог**, **порушення промпту** (scope), **шкідливі наслідки** для продакшну (відкат, force-push, оновлення модуля на сервері).

**Що сталося:** у контексті SendPulse агент **чіпав `campscout-management`** (ядро CampScout) і вносив зміни в зоні, не погодженій під цю задачу; каскад правок потребував **відкату** й цього репо до стабільного коміту **`153fbb4`**.

**Документація:** `DevJournal/sessions/LOG.md` (розділ **2026-04-11**); технічний додаток: `docs/CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md` §7.

</div>

---

## [2026-04-10] — синхронізація репозиторію (без змін коду)

- Локальний клон і сервер **CampScout** (`odoo_chatwoot_connector` → цей репо): **`git pull` / `git push`** узгоджені з **`origin/main`** (коміт **`092a80e`** на момент перевірки).
- Змін у вихідниках модуля цього дня **немає**. Детальний журнал робіт по сусідньому **`omnichannel_bridge`** — `omnichannel-bridge/docs/IMPLEMENTATION_LOG.md` та `DevJournal/sessions/LOG.md` (розділ **2026-04-10**).

---

## [2026-04-09] — КРИТИЧНИЙ ІНЦИДЕНТ (scope violation) — **відкат коду**

<div style="color:#b00020; border-left:4px solid #b00020; padding-left:12px;">

**Клас:** критична процесна помилка + **невиконання мети** (ігнорування заборони змінювати SendPulse).

**Що сталося:** зміни під Odoo Discuss / `action.views.map` були помилково внесені в цей репозиторій замість ізоляції в `omnichannel_bridge`.

**Ремедіація:** `main` повернуто до **`6905fa7`** (`git reset --hard` + `push --force-with-lease`). Коміти `9317e1c`, `2775941` знято з історії гілки.

**Документація:** `docs/TZ.md` (червоний блок), `TECHNICAL_DOCS.md`, **`docs/CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md`**, `omnichannel-bridge/docs/IMPLEMENTATION_LOG.md`, `DevJournal/sessions/LOG.md` (розділ **2026-04-09**).

</div>

---

## [2026-04-08] — v17.0.2.0.0 (patch)

### Нові можливості

**Крон: Pull Missing Contacts (щогодини)**
- Новий метод `cron_pull_missing_contacts()` — щогодини перевіряє чи всі контакти SendPulse є в Odoo
- Тягне список контактів з SendPulse API по кожному боту (pagination 100/раз)
- Якщо контакт відсутній → автоматично створює запис + підтягує повний профіль
- Якщо контакт є але без аватару → оновлює профіль
- Якщо всі в нормі → нічого не робить (debug лог)
- Захист від втрати webhook-подій при перезапусках контейнера

---

## [2026-04-05] — v17.0.2.0.0

### Нові можливості

**Синхронізація аватара в картку партнера Odoo**
- Нова кнопка 🔄 "Оновити профіль" у формі розмови — підтягує актуальні дані з SendPulse API
  (аватар, мова, статус підписки) і одразу копіює фото у `partner.image_1920`
- При ідентифікації клієнта через wizard — фото копіюється автоматично (без кнопки)
- Відображення аватара в боковій панелі Discuss (SendPulse Info Panel)

**Sidebar панель у Discuss**
- Панель з даними контакту прямо в чаті: аватар, username, мова, статус, бот-змінні, картка партнера
- Активується кнопкою "Клієнт SendPulse" у правій панелі інструментів

**Автозаповнення картки партнера**
- При ідентифікації — ім'я, email, телефон з бот-змінних (`user_email`, `booking_email`)
- Поля `sp_child_name`, `sp_booking_email` — дані зібрані ботом під час розмови

### Виправлення

**API SendPulse — структура відповіді по каналах**
- Instagram: фото в `channel_data.profile_pic` (не `photo` як у Telegram)
- Messenger/Facebook: фото в `data.avatar.path`
- Telegram: `channel_data.photo`
- WhatsApp і Messenger від Meta API — завжди `null` (обмеження Meta API)

**Статус підписки**
- SendPulse повертає статус як `int` (1=active, 0=unsubscribed, 2=deleted, 3=unconfirmed)
  а не рядок — виправлено `AttributeError: 'int' object has no attribute 'lower'`

**OWL компонент (Odoo 17)**
- Виправлено синтаксис шаблону: `not x` → `!x`, `and` → `&&` (JS, не Python)
- Виправлено API реєстрації дії: `component:` замість `Panel:` (Odoo 16→17 breaking change)

### Технічні труднощі сесії

1. **Кеш JS assets** — після правок OWL шаблону браузер і сервер роздавали старий бандл.
   Вирішення: `DELETE FROM ir_attachment WHERE name LIKE '%assets%'` в PostgreSQL

2. **Python .pyc кеш** — після деплою сервер виконував старий байткод.
   Вирішення: `docker exec ... find -name '*.pyc' -delete` перед рестартом

3. **Git permissions на сервері** — `insufficient permission for adding an object`.
   Вирішення: `sudo chown -R deploy:deploy .git/`

4. **SendPulse API структура відповіді** — документація не відповідала реальності.
   Вирішення: зробили прямий API виклик з контейнера і порівняли з `raw_json` в БД

5. **threadActionsRegistry Odoo 17** — API змінився між 16 і 17 версією.
   Вирішення: прочитали реальний Odoo 17 source `/mail/static/src/core/common/thread_actions.js`

---

## [2026-04-03]

- Docs: professional badges, author attribution, Fayna Digital branding

## [2026-04-02]

- Docs: session 6 log — stage fix, channel stats, orphan attachments cleanup
- Fix: очищення stage 'new_message' коли оператор відповідає через SendPulse webhook

## [2026-03-29]

- Fix: запобігання дублюванню WhatsApp / Telegram каналів при повторному контакті
- Fix: тип `photo` для Telegram image messages у SendPulse API
- Fix: вкладення не прив'язані до mail.message — видалено `res_model` при створенні
- Docs: виправлено deploy path — Docker монтує `/opt/campscout/custom-addons`
- Fix: завантаження SendPulse media через API, збереження як Odoo attachment
- Fix: рендеринг вхідних медіа (зображення, стікери, лайки) як `<img>` у Discuss
- Fix: href extraction — пошук атрибута незалежно від порядку у тезі `<a>`
- Fix: crash на `action_close` — прибрано confirm dialog, додано reload
- Fix: коректний рендеринг URL при відправці посилань операторами

## [2026-03-28]

- Fix: settings cloud icon (dirty state) + saved indicator
- Docs: session 5 log як incident timeline table
- Docs: всі 4 канали підтверджено як working
- Fix: WhatsApp message format — `text.body` nested object
- Fix: Messenger і WhatsApp payload format

## [2026-03-27]

- Docs: TECHNICAL_DOCS — session 4 log, нові функції, фікси
- Chore: автор Fayna, module description page
- Fix: поле Operators — тільки internal users

## [2026-03-26] — Ранні версії

- Feat: двостороння переписка (Odoo Discuss ↔ SendPulse API)
- Feat: webhook endpoint `POST /sendpulse/webhook`
- Feat: ідентифікація клієнтів (email / телефон → `res.partner`)
- Feat: черга неідентифікованих чатів
- Feat: UTM-атрибуція першого контакту
- Feat: підтримка каналів: Telegram, Instagram, Facebook, Viber, WhatsApp, TikTok
- Feat: `sendpulse.webhook.data` — сирі дані (7-денна ротація)
- Feat: розмежування доступу Officer / Administrator
