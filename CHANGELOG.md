# CHANGELOG — odoo-chatwoot-connector (SendPulse Connector)

Формат: `## [date] — YYYY-MM-DD`

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
