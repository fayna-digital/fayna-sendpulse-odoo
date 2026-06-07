# CHANGELOG — odoo-chatwoot-connector (SendPulse Connector)

Формат: `## [date] — YYYY-MM-DD`

---

## [docs] — 2026-06-08 (без зміни коду)

### Added / Changed
- Приведено до [[REPO_STANDARD]] (репо №4): **створено CLAUDE.md** (відсутній — з банером #4ZONES + структура + deploy + секрети); `docs/TZ.md` переписано у 6 областей spec-driven (синхронізовано версію 3.7.1→14.7); `docs/PLAN.md` створено (tests, token refresh, multi-lang).
> ⚠️ Код не змінювався. Версія модуля 17.0.14.7.

---

## [2026-04-22] — v17.0.14.4

### UX: скорочено текст плашки «Контакт в архіві»

Прибрано пояснення про bulk-правило. Плашка коротка і проста:
«🗂 Контакт в архіві — перевір і розархівуй якщо потрібно.»

---

## [2026-04-22] — v17.0.14.3

### UX fix: правильний текст у плашці "Контакт в архіві"

Попередній текст («Фото клієнта не відображається у чаті, поки картка архівована») був хибним — archived partner все ж рендериться у Discuss bubble з фото. Замінено на пояснення **причини**: bulk-правило «порожні картки» могло автоматично зачепити живого клієнта, менеджер має перевірити і розархівувати.

Тільки `sendpulse_info_panel.xml` — Python/JS не чіпані.

---

## [2026-04-22] — v17.0.14.2

### UX: badge "Контакт в архіві" у SendPulse InfoPanel + one-click "Розархівувати"

**Контекст:** пару днів тому запроваджена категорія тегу "порожні картки" + bulk-архівація контактів без даних. Через неї у архіві опинилось багато **живих клієнтів** SendPulse (напр. `res.partner.id=13973` «Психотерапевт Тетяна Шапошник»). Odoo Discuss не показує аватар archived partner-а у bubble — виглядає як "пропало фото у чаті".

**Що додано:**
- У правій InfoPanel (поруч з фото/ПЕРЕКЛАД/PDF-каталог/SMS-купон) у блоці "Клієнт Odoo":
  - Якщо `partner.active = False` — ім'я і іконка підсвічуються червоним.
  - Показується `alert-danger` з текстом «📦 Контакт в архіві» + пояснення «Фото клієнта не відображається у чаті, поки картка архівована».
  - Кнопка «↩ Розархівувати» → RPC → `partner.write({'active': True})` → panel reloads → фото повертається у bubble відразу.
- Клієнт цього **не бачить** — це Odoo backend UI, не SendPulse. У SendPulse йдуть тільки звичайні повідомлення оператора.

**Файли:**
- `static/src/components/sendpulse_info_panel/sendpulse_info_panel.js` — state `unarchiveLoading` + action `onUnarchivePartner()`.
- `static/src/components/sendpulse_info_panel/sendpulse_info_panel.xml` — червона alert-секція з кнопкою.
- Serverний RPC `unarchive_partner_for_channel()` і поле `partner.active` у `get_connect_for_channel()` уже були задеплоєні в v17.0.14.1.

**Future work:**
- Увімкнути tracking на `res.partner.active` (`ir.model.fields`) щоб бачити хто архівує і коли.
- Розібратись з bulk-правилом "порожні картки" — щоб не захоплювало активних чат-контактів.

---

## [2026-04-22] — v17.0.14.1

### Bugfix: прибрано дубль імені контакта в Discuss bubble

**Симптом:** у чатах SendPulse кожне вхідне повідомлення клієнта рендерилось з ім'ям двічі — один раз у header bubble (його Discuss малює з `author_id`), другий раз всередині тексту повідомлення як `<b>👤 {name}</b><br/>`. Виглядало як шум у кожному bubble; крім того, preview reply-message у Discuss показував цей префікс замість реального тексту, через що функція reply виглядала поламано.

**Причина:** модуль у webhook handler вставляв у `body` message_post-у префікс `<b>👤 {contact_name}</b>`, хоча Discuss уже показує ім'я автора з `author_id.name`.

**Фікс** у `models/sendpulse_connect.py`:
- Чотири гілки incoming-handler-у (image/media-with-attachment/media-fallback/text) — прибрано префікс з `body`. Тепер у body тільки attachment або чистий escape(text).
- Backfill flow (`_process_outgoing_event` → incoming backfill) — також без ім'я; залишено позначку `(backfill — SendPulse пропустив webhook)`.

**Старі повідомлення** у БД залишаються з дублем (історія). Якщо треба почистити — одноразовий UPDATE по `mail_message.body` з regex.

**Також додано (підготовка до v17.0.15 badge-фічі, без JS-активації):**
- `get_connect_for_channel` повертає `partner.active` у dict.
- Новий RPC-метод `unarchive_partner_for_channel(channel_id)` — для майбутньої кнопки "Розархівувати" в InfoPanel.

Ці два додатки поки не використовуються фронтендом (JS/XML зміни підуть окремо через staging).

---

## [2026-04-21] — v17.0.13.0

### F13b: RODO/GDPR consent audit log + enforcement

**Legal driver:** PL PKE (Prawo komunikacji elektronicznej) вимагає окремих consent-ів per-channel (email і SMS — різні комунікаційні канали). Без audit-log-у ми не можемо довести регулятору коли/як/на що клієнт дав згоду — ризик штрафу. RODO art. 7(1) вимагає мати доказ consent-у.

**Нова модель** `sendpulse.privacy.consent.log` (append-only):
- `partner_id`, `connect_id`, `message_id` (посилання на sendpulse.message як доказ)
- `email`, `phone`, `purpose` (lead_magnet_email / lead_magnet_sms / marketing_* / transactional)
- `channel`, `legal_basis` (consent/contract/legitimate_interest/legal_obligation)
- `consent_given` (Bool — True = надано, False = withdrawal), `consent_timestamp`
- `exact_user_response` (Text — буквально що написав клієнт)
- `policy_version` (з ICP `rodo_policy_version`, default `v1.0`)
- `source` (sendpulse_chat / website_form / admin_manual / api)
- Append-only: `write()` блокує зміну всіх полів крім `notes`; `unlink()` дозволений тільки superuser-у
- Helper методи: `record_consent(...)`, `has_active_consent(purpose, email/phone/partner)`

**Auto-capture у lead magnet flow:**
- `_send_pdf_catalog_email()` — перед send перевіряє чи є withdrawal для email+`lead_magnet_email`. Якщо є → `error='consent_withdrawn'`, skip. Після успішного send → авто-запис consent_given=True з exact_response = last incoming message.
- `_generate_and_send_sms_coupon()` — те саме для `lead_magnet_sms` + phone.

**Unsubscribe detection** у incoming flow (`_check_and_record_unsubscribe()`):
- Regex-паттерни мультимовно: `STOP`, `unsubscribe`, `відписка`, `отписка`, `nie chcę`, `wypisz`, `rezygnuj`, `не пишіть`, `видаліть мене`, `удалите меня`...
- Match → фіксується withdrawal для всіх актуальних purpose-ів connect-у (email + sms + messenger)
- Майбутні `_send_pdf` / `_send_sms` пропустяться (enforcement check)

**Settings:**
- `consent_enforcement_enabled` (Bool, default=True) — toggle для enforcement (можна тимчасово вимкнути без видалення записів).
- `rodo_policy_version` (Char, default=`v1.0`) — версія політики, записується у кожен новий consent.

**UI:**
- Новий menu «Журнал згод RODO» під SendPulse → видно Officer-ам (read-only) і Admin (create/write для manual вводу).
- List + form + search — фільтри `granted` / `withdrawn` / `lead_magnet` / `email_ch`, групування по partner/purpose/channel/source.
- Form read-only крім `notes` (адмін може додавати коментар з контекстом).

**Важливо:** існуючі клієнти яким уже надсилалось PDF/SMS **не мають** записів у журналі (backfill не виконано — тільки з моменту v17.0.13.0). При spor-і з регулятором по старих клієнтах — залежати доведеться на SendPulse-історії чату.

---

## [2026-04-21] — v17.0.12.1

### Metadata refresh: Fayna Digital branding + Odoo-typo fix

- `__manifest__.py`: `name` / `summary` / `description` / `website` оновлено під поточний scope (AI + lead magnet + live seats + drip + multi-page). `website` = `https://fayna.agency`.
- `static/description/index.html`: version badge 17.0.3.1.0 → 17.0.12.1, hero subtitle переписано, додано секцію «AI + Автоматизація» з 9 карточками (F2/F9-F14/RAG/multi-page/race-safe).
- **Typo fix: «SendPulse Odo» → «SendPulse Odoo»** в усіх 19 файлах (156 замін) — manifest name, views labels, security groups, log prefixes, docs.
- `README.md`: bump до v17.0.12.0, секція «AI + Автоматизація» з описом F2/F9-F14, футер «Про Fayna Digital» з контактами.
- `TECHNICAL_DOCS.md`: header bump + технологічний стек розширено (TurboSMS, loyalty.program, event.event).

Функціонал без змін — тільки метадата і доки.

---

## [2026-04-21] — v17.0.12.0

### F14: Event seats awareness у AI-контексті (live `seats_available`)

**Проблема:** AI у F10 suggestions і F1 RAG мав тільки hardcoded canonical facts у prompt — не знав скільки місць залишилось по конкретних змінах. Міг рекомендувати повний табір або не створював FOMO коли місць мало.

**Фікс:**

- Новий helper `sendpulse.connect._get_live_events_context(limit=15, low_ratio=0.3)` — читає `event.event` де `active=True, date_begin>NOW, stage_id.pipe_end=False`, форматує компактно:
  ```
  LIVE ТАБОРИ 2026 (з Odoo, seats_available АКТУАЛЬНО ЗАРАЗ...):
  • 08.05 — Передтаборова зустріч... — 28/30 місць
  • 12.07 — На вовчій стежці — ❗ 5/20 (майже повний!)
  • 26.07 — CHILL-CAMP у Швейцарії — 30/30 місць
  • 28.07 — Дослідники морів KIDS — II зміна — ❗ 11/30 (майже повний!)
  ```
- Інжект у prompt `_generate_reply_suggestions()` (F10) + `_rag_answer_question()` (F1) — перед canonical facts / FAQ block.
- Стилістична інструкція у prompt: ❗ (<30%) → FOMO «Лишилось тільки 5 місць»; 🔴 (повний) → чесно відмовитись і запропонувати аналог; звичайний → не акцентувати.
- Feature-flag `event_seats_awareness_enabled` (default True) у Settings — можна вимкнути якщо глюкне.

Умова `stage_id.pipe_end=False` виключає стадії «Закінчений» / «Скасовано» (події в закритих стейджах не показуємо).

---

## [2026-04-21] — v17.0.11.4

### Fix: Settings падає + email logo все ще `?` у Gmail

**Settings RPC_ERROR:** `Field res.config.settings.lead_magnet_email_body_html must have type 'boolean', 'integer', 'float', 'char', 'selection', 'many2one' or 'datetime'`. `fields.Html` і `fields.Text` з `config_parameter` у `res.config.settings` не підтримуються Odoo 17 — треба plain types. Наслідки: заходити в будь-які Settings неможливо (навіть не повʼязані з lead-magnet).

- `lead_magnet_email_body_html` (Html) — видалено (не використовувалось, body_html рендериться з mail.template).
- `lead_magnet_sms_template` (Text) → `Char`.
- `views/sendpulse_connect_views.xml` — прибрано reference на видалене поле.

**Email logo — `?` у Gmail (причина):** `res.company.logo` у CampScout — **SVG** (46 KB, `<?xml version="1.0"...<!DOCTYPE`). Gmail блокує рендер SVG з міркувань безпеки (CVE-і 2010+ з JS у SVG). Avatar рендериться бо JPEG.

- Shipped PNG-логотип у `static/src/img/campscout_logo.png` (23 KB, растровий).
- Новий helper `_get_email_logo_png_b64(company)` — читає PNG з модуля, fallback на `company.logo` якщо та в растрі (PNG/JPEG magic bytes).
- `_send_pdf_catalog_email()` викликає helper замість прямого `company.logo`.
- `_get_or_create_public_image()` авто-пересоздасть кешований public attachment (порівняння `att.datas == image_b64` → mismatch → new attachment).

---

## [2026-04-21] — v17.0.11.3

### Fix: lead-magnet email — avatar/logo показувались `?` у Gmail

**Проблема:** у v17.0.11.2 перейшли на inline Data URI (`<img src="data:image/png;base64,...">`) для avatar signer-а і CampScout logo. Тіло виросло 8 KB → 139 KB. У Gmail обидві картинки рендерились як broken-image `?` placeholder, а самі картинки показувались окремими "inline attachments" повним розміром під футером листа.

**Root cause:** Gmail обрізає/ігнорує `src="data:..."` коли base64 > ~8KB в атрибуті. Avatar image_128 ≈60KB base64, логотип компанії ≈50KB — обидва за межею.

**Фікс:** замість Data URI — публічний `ir.attachment` (`public=True`, `res_model='ir.ui.view'`, `res_id=0`). URL `/web/image/{id}/name.png` з `web.base.url`. Gmail завантажує через свій image proxy, розмір не важить.

- Новий helper `sendpulse.connect._get_or_create_public_image(name, image_b64)` — ідемпотентний (кешує attachment_id в `ir.config_parameter`, пересоздає тільки якщо `datas` змінилось).
- `_send_pdf_catalog_email()` — замінено Data URI blocks на `f'{base_url}/web/image/{att.id}/avatar.png'` + аналогічний для логотипа.

---

## [2026-04-21] — v17.0.11.0

### Critical fix: SendPulse missed-inbound backfill + 3 related changes

**Багa root cause:**

У `controllers/main.py` handler для outgoing SendPulse events був завʼязаний тільки на `EVENT_OUTGOING_MSG = 'outbound_message'`, але SendPulse фактично шле event type `'outgoing_message'`. Константа `EVENT_OUTGOING_MSG2 = 'outgoing_message'` була визначена, але **не використовувалась** у `elif`. Тому `_process_outgoing_event()` ніколи не викликався на проді.

Цей же code path робить backfill missed incoming (детект тексту клієнта у `contact.last_message` який SendPulse забув прислати як `incoming_message` webhook). Отже missed messages пропадали.

**Кейс Сергій Досужий:** клієнт написав перше повідомлення «Добрый день дата заїзду, ціна, тематика 11 років хлопец» → SendPulse його отримав, показав у email-notification і у `contact.last_message` наступних events, але окремий `incoming_message` webhook не надіслав. У нас повідомлення пропало, AI не знав віку («11 років») і питав.

**Фікси:**

1. **`controllers/main.py`**: `elif event_type in (EVENT_OUTGOING_MSG, EVENT_OUTGOING_MSG2)` — обробляємо обидва типи.

2. **`_process_outgoing_event()` повністю переписаний**:
   - Раніше помилково створював `sendpulse.message(direction=outgoing)` з текстом **клієнта** (бо `contact.last_message` = текст клієнта, не наш outgoing).
   - Тепер: якщо `contact.last_message` не знайдено у incoming → створюємо як **incoming** (backfill), постимо у channel з поміткою `(backfill — SendPulse пропустив webhook)`, автор = partner_id або OdooBot, оновлюємо funnel_stage → `customer_replied`, stage → `new_message`.
   - Видалена помилкова outgoing-дедуплікація.

3. **Audit + backfill 91 історичних missed messages** через shell-script по всім чатах. Скановано 2520 outgoing-webhooks, 148 унікальних `(contact_id, last_message)` не знайдено у `sendpulse.message(incoming)` — 91 реальне повідомлення клієнта відновлено, 91 `/start`-шум і 6 orphan без connect — skipped.

**Email template v17.0.10.3 також у цьому релізі:**

- Купон **прибрано з email** (PDF-attach). Тепер купон іде ТІЛЬКИ через SMS — щоб оператор міг зібрати і email, і phone окремо з окремою маркетинговою згодою.
- У email тільки hint: «Напишіть у чат телефон — надішлемо SMS з купоном».
- Брендовий CampScout `mail.template` (з `28_event_registration.html`): header #952426, CTA «Обрати табір» → campscout.eu/shop, блок гарантій (NIP/REGON/1129/Compensa), signature, **RODO блок + unsubscribe посилання**, footer.

**Hot-fix на проді:** reset `sp_pdf_sent_at`/`sp_pdf_sent_to_email` на connect 421 (Дашка Запорожская) — прибрано тестовий send на admin@fayna-mail.

---

## [2026-04-21] — v17.0.10.2

### F13 email: брендовий CampScout template замість plain HTML

Попередній фідбек: лист-каталог виглядав "голо" — plain-text-style HTML без стилю бренду. Замінено на повноцінний `mail.template` з CampScout брендбуку (стиль з `28_event_registration.html` у `Projects/camp/docs/email-previews/`):

- Header з червоною смугою #952426 + логотип компанії
- Блок промо (до 01.05.2026)
- **Виділений блок купона** — особистий промокод на 5% у рамці з dashed border, розмір 22pt, letter-spacing, `{залишилось N на акцію}` тригер терміновості
- CTA-кнопка «Обрати табір» → campscout.eu/shop
- Блок гарантій (REGON/NIP/Compensa/1129)
- Signature — Volodymyr Shevchenko + логотип
- **RODO блок** з поясненням «ви отримали бо запитали через чат», посилання на Polityki prywatności
- **Unsubscribe посилання** — `mailto:admin@campscout.eu?subject=Unsubscribe` з prefill email клієнта
- Footer з Regulamin / RODO / Cookies / Ochrona dzieci

**Технічно:**

- `data/mail_template_lead_magnet.xml` — `mail.template` record, `noupdate="1"` (admin може правити через Settings → Technical → Email Templates без deploy).
- `_send_pdf_catalog_email()` переписаний на `template.send_mail(self.id, force_send=True, email_values={'attachment_ids': [...]})`.
- Змінні: `object.name`, `object.sp_booking_email` через t-out; купон-дані через `ctx.get('coupon_code')` / `ctx.get('coupon_remaining')` / `ctx.get('coupon_expires')` (передаються через `with_context(...)`).
- Fallback — inline plain-HTML якщо template не знайдено (наприклад при першому install до data-load).

---

## [2026-04-21] — v17.0.10.2

### F13-UI: OWL кнопки «Надіслати PDF» + «Надіслати SMS-купон»

Секція «🎁 Маркетинг (F13)» у `sendpulse_info_panel` (між client-info і 🌐 Перекладом):

- **PDF-каталог** — inline-input з email (prefill з `sp_booking_email` / `partner.email` / `unidentified_email`) + кнопка «Надіслати». Після успіху — alert-success з email і датою, форма ховається.
- **SMS-купон 5%** — inline-input з phone (prefill з `partner.mobile/phone` / `unidentified_phone`) + кнопка. Після успіху — показує код + залишок купонів.

**Лічильник вільних купонів виводиться автоматично** з `loyalty.card.points` — коли хтось робить замовлення і застосовує код, Odoo знижує points, наступний клієнт отримує SMS з актуальним числом. При 0 — error `coupon_exhausted`.

**Стани:**
- `pdf_sent_at` truthy → замість input показує alert «PDF надіслано на email» з датою.
- `coupon_code` truthy → alert «SMS-купон надіслано на phone» з кодом і датою.
- Error-map: зрозумілі повідомлення для disabled/no_email/attachment_missing тощо.

**Секція прихована** якщо `lead_magnet_enabled=False` у Settings (`state.connect.lead_magnet_enabled`).

**Підключено до `get_connect_for_channel`:** нові поля `pdf_sent_at`, `pdf_sent_to_email`, `coupon_code`, `coupon_sent_at`, `coupon_sent_to_phone`, `prefill_email`, `prefill_phone`, `lead_magnet_enabled`.

---

## [2026-04-21] — v17.0.10.1

### Fix: race condition → дублі `sendpulse.connect` на одного контакта

Поточний incident: Yulia Kolesnyk (Instagram, contact=69e78d68bb641b63820d6b8a) — два записи 429 і 430, створені за 164 мс двома workers (34 і 33) з подій `new_subscriber` + `incoming_message`. Advisory_xact_lock не серіалізував через Odoo cache (search після lock повертав stale state).

**Три рівні захисту тепер:**

1. **Postgres partial unique index** (hard lock, init()):
   ```sql
   CREATE UNIQUE INDEX sendpulse_connect_active_contact_service_uniq
     ON sendpulse_connect (sendpulse_contact_id, service)
     WHERE stage != 'close' AND sendpulse_contact_id NOT NULL
   ```
   Фізично не дозволить створити дубль на БД-рівні.

2. **Flush + invalidate після advisory_lock** — `env.flush_all() + env.invalidate_all()` після взяття lock. Гарантує що search повертає актуальний стан (включно з записом який commit-нув інший worker).

3. **IntegrityError handler з savepoint** — якщо попри все unique index триггерить при create, ловимо через `cr.savepoint() + except IntegrityError`, invalidate cache, пере-search → використовуємо existing.

**Hot-fix уже виконано:**

- Merge 3 messages + 1 sendpulse.message з connect 430 → 429
- Merge partner 14186 → 14185 (FK переведені, 14186 unlinked)
- channel 5331 unlinked, connect 430 unlinked
- Remaining: connect 429, partner 14185, channel 5330

---

## [2026-04-21] — v17.0.10.0

### F13 Lead magnet: PDF-каталог на email + SMS-купон (backend)

Нова велика фіча — клієнт отримує або PDF-каталог на email, або промокод 5% SMS-ом, в обмін на контакт.

**Архітектура:**

- `sendpulse.connect` tracking fields: `sp_pdf_sent_at`, `sp_pdf_sent_to_email`, `sp_coupon_code`, `sp_coupon_sent_at`, `sp_coupon_sent_to_phone`.
- **PDF-email** (`_send_pdf_catalog_email(to_email)`) — через `mail.mail` з ir.attachment. Template HTML з placeholders `{name}`, `{code}`, `{remaining}`, `{expires}`. Ідемпотентно — не надсилає двічі на той самий email.
- **SMS-купон** (`_generate_and_send_sms_coupon(to_phone)`) — бере **spільну loyalty.card** з налаштованої програми (один код на всіх — shared pool). Відправка через `kw_sms_api` (TurboSMS) як `sms.sms` з `kw_sms_provider_id` з Settings.
- SMS template з placeholders `{code}`, `{remaining}` (points на картці програми), `{expires}` (expiration_date картки) — scarcity-тригер «залишилось N купонів, хто встиг — той виграв».
- RPC endpoints для OWL-панелі (наступний реліз): `send_pdf_catalog_for_channel`, `send_sms_coupon_for_channel`.

**Settings:**

- Master-switch `lead_magnet_enabled` (default False).
- `lead_magnet_pdf_attachment_id` Many2one на `ir.attachment` (domain mime=pdf).
- `lead_magnet_email_subject` / `lead_magnet_email_body_html` — шаблон email.
- `lead_magnet_coupon_program_id` Many2one на `loyalty.program` (domain: coupons/promo_code, active).
- `lead_magnet_sms_template` — шаблон SMS з placeholders.
- `sms_provider_id_setting` — ID з `kw_sms_provider` (TurboSMS=2 за замовчуванням на проді).

**Залиті дані на проді:**

- `ir.attachment` ID 37929 — `CampScout-Oferta-2026.pdf` (8 MB, стиснуто з 44 MB через Ghostscript /screen preset).
- Програма-купон на вибір: `Early Bird Promo 2026` id=19 (5%, coupons, shared card з points=91, expires=2026-06-20).

**Scarcity-логіка (shared coupon pool):**

Один код `0449-fa20-49c8` для всіх клієнтів. Коли клієнт застосовує код при checkout → Odoo loyalty автоматично зменшує `points`. У SMS/email показуємо актуальний залишок. При 0 — код перестає діяти.

**Frontend (OWL-кнопки)** — наступний коміт v17.0.10.1.

---

## [2026-04-21] — v17.0.9.0

### F12 AI context enrichment через email-ідентифікацію

Раніше AI-драфти (F10) мали тільки текст останніх 10 повідомлень + ім'я/канал. Для постійних клієнтів контекст губився — AI не знав що людина вже бронювала табір минулого сезону, який був стейдж ліда, яка сума замовлень.

**Що додано:**

1. **`_try_extract_email_and_link()`** — regex-сканер останніх 20 inbound повідомлень. Якщо клієнт написав email прямо у чаті (не через бот-flow), парсер витягує, записує у `sp_booking_email`, шукає `res.partner` по email і link-ує. Викликається всередині `_generate_reply_suggestions` (ідемпотентно — skip якщо email уже є).

2. **Розширений профіль у промпті** — коли `connect.partner_id` заповнений:
   - `res.partner`: name, email, phone/mobile, street+city, create_date.
   - `crm.lead` (останні 5): name, stage, probability, create_date.
   - `sale.order` історія (3 останні у state `sale`/`done`): name, date, amount.
   Маркер `── ІДЕНТИФІКОВАНИЙ КЛІЄНТ ──` або `⚠️ КЛІЄНТ НЕ ІДЕНТИФІКОВАНИЙ — email невідомий`.

3. **Нове правило стилю у промпті:**
   - Якщо клієнт НЕ ідентифікований + запитує деталі/ціну → один з 3 варіантів може ввічливо запропонувати email для особистої пропозиції (не нав'язливо).
   - Якщо ідентифікований → AI має використати контекст (минулі табори, стадію ліда) для персоналізації, не цитуючи деталі буквально.

**Що AI тепер бачить (приклад):**

```
⚠️ КЛІЄНТ НЕ ІДЕНТИФІКОВАНИЙ — email невідомий
```

або

```
── ІДЕНТИФІКОВАНИЙ КЛІЄНТ ──
Partner ID: 3421, створено: 2025-06-12
Телефон: +48 600 123 456
Адреса: ul. Marszałkowska 100, Warszawa

CRM-ліди (останні):
  • [2025-07-01] Дослідники морів 2025 — stage: Won, prob: 100%
  • [2026-03-15] TDK 2026 — stage: Qualified, prob: 40%

Історія замовлень:
  • [2025-07-02] SO0142 — 3 300 zł
```

**Дизайн-рішення:**

- Без окремого прапорця toggle — просто enrichment коли є partner_id. Вимкнути можна через `suggested_reply_enabled`.
- Не запитуємо додаткових LLM-викликів для ідентифікації — тільки regex + exact email match. Fuzzy/semantic match відкладено на окрему фічу (якщо виявиться слабко).
- F13 (lead magnet PDF/купон) — наступний крок, логічно використає цей же `_try_extract_email_and_link` як trigger.

---

## [2026-04-21] — v17.0.8.0

### F11 Auto-translate UA↔PL у Discuss side-panel

Польські оператори бачать текст клієнта українською — раніше копіювали у Google Translate. Тепер — кнопки просто у панелі.

**Backend:**

- `sendpulse.connect._translate_text(text, target_lang)` — виклик Claude Haiku з STRICT JSON `{source_lang, translated}`. Токени: 2000 max, timeout 15с. Підтримка `pl|uk|en|ru`.
- RPC `translate_last_inbound_for_channel(channel_id, target_lang)` — витягує останнє incoming повідомлення з channel → перекладає → повертає `{translated, source_lang, original, error}`.
- Robust parser: strip ```json fence, balanced braces, WARNING з raw[:300] при невдачі.
- Toggle `auto_translate_enabled` у Settings (default False).

**Frontend (OWL):**

Нова секція «🌐 Переклад» у `sendpulse_info_panel`, між client-info і AI-драфтами. Дві кнопки-перемикачі «→ PL» і «→ UK»:

- Клік → RPC → loading spinner → показ перекладу у border-блоці.
- Клік на переклад → clipboard copy + toast «Переклад скопійовано».
- Підпис з detected source_lang («З uk · клік — копіювати»).
- Error-стан з зрозумілими повідомленнями («Переклад вимкнено у Settings», «Немає вхідних повідомлень» тощо).

**Свідомий MVP-scope:**

- Перекладається тільки ОСТАННЄ inbound — не всі повідомлення (економія токенів, 90% use-case).
- On-demand — не автоматично при відкритті чату.
- Без patch-у нативного Discuss message renderer (складно/крихко в Odoo 17).

Подальше розширення (не в цьому релізі): inline-button під кожним повідомленням, auto-detect operator_lang з `res.users.lang`, кеш `translation_cache` на `mail.message`, зворотний переклад операторської відповіді перед send.

---

## [2026-04-21] — v17.0.7.3

### AI-промпти: звертання на «Ви» + заборона збору даних дитини у чаті

Юзер показав F10-драфт який звертався до клієнтки на «ти» і просив ПІБ дитини, дату народження, мед. особливості у чаті. Два критичних фікси в обох AI-промптах (`_generate_reply_suggestions`, `_rag_answer_question`):

**1. Звертання — тільки «Ви».**

Батьки — дорослі люди, ми продавець-консультант, не ровесники. Додано як окреме правило стилю + окрему заборону у списку «КАТЕГОРИЧНО ЗАБОРОНЕНО: ❌ ти/тобі/твій».

**2. НЕ збирати дані дитини у чаті. Юридична причина.**

ПІБ, дата народження, медичні особливості/діагнози, алергії, контакти для екстреного зв'язку — батьки заповнюють САМІ у кваліфікаційній (табірній) картці в особистому кабінеті, це додаток №5 до Договору (Regulamin Panelu Klienta).

**Юридичне пояснення тепер у промпті** — щоб AI міг пояснити клієнту: після заповнення батьки ПІДПИСУЮТЬ картку і цим беруть юридичну відповідальність за достовірність. Якщо оператор запише за них у чаті — без підпису картка юридичної сили не має, дані не можна використовувати.

У чаті питаємо тільки дані ЗАМОВНИКА (батьків): ПІБ, адреса проживання, телефон, email.

---

## [2026-04-21] — v17.0.7.2

### UX fix v2: `group col="1"` для full-width textarea

`separator` + standalone `field nolabel="1"` у Odoo 17 form layout все одно потрапляли у першу колонку 2-колоночної сітки — поле виявилось ~150px. Замінено на `group col="1"` — форсує одноколоночний layout, field розтягується на всю ширину sheet.

---

## [2026-04-21] — v17.0.7.1

### UX fix: text-field width у form-views

У формах `sendpulse.public.template` і `sendpulse.faq.entry` текстові поля (text/question/answer) були обгорнуті в `<group>`, через що рендерились у вузькій half-column колонці — текст переносився по одному-двом словам на рядок.

Заміна на `<separator>` + `<field nolabel="1">` поза group → поле розтягується на всю ширину sheet. Додано `options="{'rows': ...}"` для керованої висоти.

---

## [2026-04-21] — v17.0.7.0

### F9 A/B шаблони публічних відповідей з conversion tracking

До v17.0.7.0 публічні відповіді під FB/IG коментарями ротувалися через хардкод-список з 5 шаблонів: `count % 5`. Не було видно який з них фактично приводить клієнтів у приват. Тепер це модель з метриками.

**Нова модель `sendpulse.public.template`:**

- `name`, `text` (з placeholders `{landing_url}`, `{tg_url}`)
- `kind`: `standard` | `repeat` (repeat — коли клієнт уже писав у приват цьому контакту)
- `use_count` — скільки разів опубліковано
- `customer_replied_count` — скільки клієнтів після цієї публічної відповіді написали у приват
- `conversion_rate` — computed stored, `replied / use_count * 100`
- `active`, `sequence` — для sorting і вимкнення шаблону без видалення

**Rotation algorithm (`pick_template`):**

- Перші 50 використань загалом — round-robin (щоб набрати статистику рівномірно)
- Далі epsilon-greedy: 20% random explore, 80% найкращий за `conversion_rate`
- Repeat-режим — повертає перший active template з `kind='repeat'`

**Tracking у flow:**

- `_process_comment_event`: `pick_template()` → `bump_use()` → записуємо `sp_public_template_id` на connect
- `_process_inbound` (перехід `funnel_stage → customer_replied`): `bump_customer_replied()` на пов'язаному шаблоні. Ідемпотентно через `sp_public_template_conversion_counted` flag.

**Fallback:** якщо модель порожня (seed не виконаний чи всі деактивовано) — код падає назад на хардкод `_COMMENT_PUBLIC_TEMPLATES`/`_COMMENT_PUBLIC_REPEAT_TEMPLATE`.

**UI:**

- Menu: `SendPulse → Публічні шаблони (A/B)` (permission: officer)
- Tree view з color-coded `conversion_rate` (>40% зелений, ≤40% жовтий, 0% сірий)
- Graph view (bar chart) для візуалізації
- Form з placeholders-hint і метриками

**Seed (`noupdate="1"`):**

5 стандартних шаблонів — ідентичні поточному хардкоду + 1 repeat-шаблон.

**Weekly Telegram report:**

Додано секцію 🏆 Топ-3 шаблонів + ⚠️ Worst-1, фільтр `use_count >= 10` для статистичної значущості.

---

## [2026-04-21] — v17.0.6.2

### Fix: F10 panel & parser robustness

**1. `sendpulseConnectId` тепер реально доходить до фронтенду (Odoo 17).**

До цього `discuss.channel` override використовував `_to_store()` — метод з Odoo 18+, якого нема в 17. В результаті `sendpulse_connect_id` ніколи не додавався у channel-info який йде на фронт, і умова `isSendpulseChannel` працювала тільки через fallback по префіксу назви каналу (`[TG]`, `[IG]` тощо). Канали перейменовані вручну або без префіксу — SendPulse-панель не з'являлась.

Фікс у `models/mail_channel.py`:
- Додано override `_channel_info()` (Odoo 17 API) — додає `sendpulse_connect_id` у кожен info-dict.
- `_to_store()` зберіг безпечний fallback через `getattr(super(), '_to_store', None)` — не падає якщо метод не існує (Odoo 17) і готовий до апгрейду на 18.

**2. Robust JSON-парсер в `_generate_reply_suggestions`.**

Попередній regex `\{[\s\S]*?\}` був non-greedy і міг обірватись на першій `}` якщо LLM повертав вкладені об'єкти. Також не зрізав ```json code fence` який Claude додає. Новий парсер:
- Спершу знімає ```json / ```.
- Пробує `json.loads(cleaned)` напряму.
- Якщо не вийшло — balanced-brace extraction (рахує `{`/`}` depth).
- При невдачі → WARNING з raw[:500] у лог, щоб debug на прод був видимий.
- Порожні suggestions тепер теж логуються (INFO) з raw для аналізу.

Причина: 12:50:03 прод-виклик RPC повернув `[]` (9 bytes) без warning — значить парсер мовчки відкинув відповідь Claude. Тепер такі кейси видно в логах.

---

## [2026-04-21] — v17.0.6.0

### F10 Suggested Reply — OWL UI інтеграція (завершення Sprint 3 F10)

Server-side метод `_generate_reply_suggestions` був готовий з v17.0.5.5 — тепер доданий повноцінний UI у Discuss sidebar.

**Що бачить оператор:**

У `sendpulse_info_panel` (правий sidebar Discuss-каналу SendPulse-розмови) з'явилась нова секція «🤖 AI-драфти відповіді» з:
- Кнопка «🪄 Згенерувати» — клік викликає RPC `suggested_reply_for_channel(channel_id, 3)` → Claude Haiku з контекстом 10 останніх повідомлень → 3 варіанти
- Loading spinner поки чекаємо (15 сек timeout)
- Кожен варіант у border-рамці з іконкою copy
- Клік на варіант → copy to clipboard через `browser.navigator.clipboard.writeText`
- Badge «✅ скопійовано» 2.5 секунди
- Toast-notification «Варіант скопійовано — вставляйте у композер»

Якщо LLM не дав варіантів — показує текст-hint про Settings → `suggested_reply_enabled` + `anthropic_api_key`.

**Архітектура (MVP — copy-to-clipboard):**
- Оператор копіює → вставляє у Discuss composer через Cmd+V / Ctrl+V
- Не вставляємо напряму у composer бо OWL composer state не експортується модулем, це було б крихке у різних Odoo revisions

**Файли:**
- `static/src/components/sendpulse_info_panel/sendpulse_info_panel.js` — state (suggestions, suggestLoading, suggestError, copiedIdx) + 2 нових action-методи
- `static/src/components/sendpulse_info_panel/sendpulse_info_panel.xml` — секція з 3 clickable варіантами

**Release bump до 17.0.6.0** — завершення Sprint 3 TZ V2 основного блоку (F10 deploy = Sprint 3 з 5 фіч готових: F10, F2, з раніше — F9/F11 відкладені).

---

## [2026-04-21] — v17.0.5.6

### FAQ rewrite з маркетинговим стилем + RAG prompt поліпшення

**Контекст:** FAQ записи раніше були сухими «ціни залежать від програми», без конкретики — клієнти отримували безкорисні відповіді (приклад: Татьяна «Не бачу цін», Anastazia Masaz отримала неправильне слово «доставка» про дітей).

**10 FAQ переписано** за методологією `operator_snippets.md` (822 рядки best practices менеджера):

| # | Назва | Ключова зміна |
|---|---|---|
| 1 | Ціна табору + 3 флагмани | Конкретні ціни TDK 3300/Дослідники 3500/Пошумимо 3250 + промо-дедлайн 01.05 + TG -5% |
| 2 | Дати заїздів 2026 | Реальні дати кожного флагмана, не «програма і термін» |
| 3 | Вік — розбивка по флагманах | TDK для 6-11, Дослідники для 7-12, Пошумимо для 12-17 — конкретика |
| 4 | Що брати | Структурований чеклист + блог-лінк + CTA про конкретний табір |
| 5 | Харчування | Норми МОЗ, алергії персонально, цитата мам «вдома не їв, з табору — все їсть» |
| 6 | Безпека | Ustawa Kamilka, Compensa VIG 31 617 PLN, ліцензія №1129, KRK перевірки, 1500+ дітей, 4.9/5 |
| 7 | Локація/Трансфер | **БЕЗ слова «доставка»** — 3 варіанти трансферу (включений / пункт збору 61.50 zł / попутник) |
| 8 | Телефони | «Без мобілок» як USP, а не обмеження — + щоденні фото у TG чаті батьків |
| 9 | Туга за домом | 3-денна динаміка, психолог на базі, скаутський патруль, соц-доказ 1500+ |
| 10 | Бронювання | 5-кроковий процес + розтермінування без % + промо до 01.05 + м'яка бронь 48h |

Кожна відповідь закінчується **CTA-запитанням** (веде у діалог, не закриває).

**RAG prompt оновлений** з категоричними заборонами:
- ❌ Слово «доставка» стосовно дітей (тільки «трансфер», «привезти», «забрати», «супровід»)
- ❌ Вигадувати факти (ціни, дати, програми) які не в canonical
- ❌ «Дякую за питання» клішe
- ❌ «Там все є» / «Все на сайті» — завжди 2-3 конкретних факти, потім URL
- ❌ «11 років — перехідний вік» (для 11 є TDK від 6)
- ❌ Агресивно порівнювати з конкурентами
- ❌ 3 URL підряд без пояснення

**Стиль прописаний як:** «продавці-консультанти, не сухі факти — ЦІННІСТЬ + ТЕРМІНОВІСТЬ + CTA».

**Технічна деталь:** FAQ seed-файл має `noupdate=1` — тому seed не перезапише ручні зміни у проді. Оновлення через `env.ref('odoo_chatwoot_connector.faq_seed_X').write({...})` у одноразовому shell-скрипті (додано до docs/).

---

## [2026-04-21] — v17.0.5.5

### Fix — RAG не втручається у активну розмову з оператором

**Симптом:** під час live-розмови оператора з клієнткою (Марічка Криленко) клієнтка написала коротке повідомлення "20.07-29.07-дякую", і RAG відразу запостив свою відповідь поверх операторського treading.

**Root cause:** `_try_rag_auto_answer` гейтував тільки по confidence threshold + rate-limit. Не перевіряв чи оператор уже у розмові.

**Fix:** додано 3 нові guards перед RAG:
1. `stage in ('in_progress', 'close', 'identifying')` → skip
2. `sp_first_reply_at` не порожнє (оператор уже відповідав) → skip

Залишається RAG активним тільки для `stage=new/new_message` БЕЗ operator pickup — тобто саме той кейс коли RAG потрібен (перший автоматичний контакт).

### Fix — Immediate Telegram alert про протухлий FB token

**Симптом:** коли Page Token помер — модуль тихо падав на 400-ках Graph API. Weekly cron `cron_check_fb_token_expiry` не встигав піймати (запускається раз на 7 днів). Без `fb_app_secret` cron взагалі не знає `days_left`, тому не може попередити «скоро помре».

**Fix:** у `_fb_post_with_retry` додано `_maybe_alert_token_expired(err, raw)`:
- Парсить будь-який 4xx response з Graph API
- Якщо detect `code=190` / `Session has expired` / `Invalid OAuth access token` → loud Telegram-алерт
- Rate-limit 1 alert/годину через `ir.config_parameter.fb_token_invalid_last_alert_at` щоб не спамити при DDoS коментарів
- Текст алерту з інструкцією негайних дій (Graph Explorer → sync) + довгострокових (fb_app_secret + F6 auto-refresh)

### F10 Suggested reply drafts (partial — server-side)

Python-метод готовий, OWL UI ще не інтегрований. Можна викликати з odoo shell:

```python
connect._generate_reply_suggestions(count=3)
# → ['Варіант 1', 'Варіант 2', 'Варіант 3']
```

Або через RPC:
```python
env['sendpulse.connect'].suggested_reply_for_channel(channel_id=5317, count=3)
```

Prompt включає:
- Профіль клієнта (ім'я, child_name, email, username, service)
- Історію 10 останніх повідомлень обох сторін
- Інструкції: коротко, по-людському, 1-2 емодзі, різні підходи (інформативний/запитуючий/емпатичний)

Settings: `suggested_reply_enabled` (default False). OWL sidebar panel — наступний реліз.

---

## [2026-04-21] — v17.0.5.4

### Fix — Auto-split довгих повідомлень оператора

**Симптом:** оператор написав ~1400 chars у Discuss (пояснення про Долину Карпа) → SendPulse повернув `400 (#100) Довжина перевищує 1000 символів` → клієнт у Instagram нічого не отримав. В Odoo повідомлення показувалось як надіслане (через `super().message_post()` було вже збережене у chatter), лише маленька нотатка «❌ не доставлено» десь знизу.

**Root cause:** ліміт Instagram у SendPulse — 1000 chars. Інші канали мають свої ліміти. Модуль надсилав сирий текст без перевірки довжини.

**Fix:**

1. **Per-service text limits** (`_SERVICE_TEXT_LIMITS`):
   - Telegram: 4096
   - Instagram / TikTok: 1000
   - Facebook / Messenger: 2000
   - WhatsApp: 1600
   - Viber: 7000
   - LiveChat: 4000

2. **Auto-split через `_split_text_by_limit(text, max_chars)`** — 4-рівневе розбиття:
   - По абзацах (`\n\n`)
   - По реченнях (regex `(?<=[.!?…])\s+`)
   - По словах
   - Hard cut як останній засіб
   - Safety margin 20 chars для нумерації `(1/N)`

3. **High-level `send_message_to_sendpulse()`:**
   - Якщо `len(text) > limit` → `_split_text_by_limit()` → loop через chunks
   - Між chunks пауза 0.7s (ratelimit-safe)
   - Перший chunk несе attachment, решта — лише текст
   - Nump prefix `(i/N) ` у кожному chunk щоб клієнт бачив порядок
   - Нотатка у Discuss-канал про розбиття з кількістю частин
   - Повертає True лише якщо ВСІ chunks пройшли

4. **Low-level `_send_single_message()`:**
   - Без перевірки довжини, без retry для length — просто POST і parse result
   - Використовується внутрішньо з chunks
   - Також прямо (backward compat) якщо текст коротший за limit

**Backward compat:** всі існуючі виклики `send_message_to_sendpulse(text)` продовжують працювати — просто короткі тексти проходять прямо через нове high-level до low-level send.

---

## [2026-04-21] — v17.0.5.3

### Sprint 3 F2 — Drip campaigns (3 streams)

Погодинний cron `cron_drip_followups` повертає «зависли» розмови і алертує менеджерів.

**Stream 1 — Reminder клієнту 6h (`drip_reminder_6h_enabled`):**
- Фільтри: `sp_funnel_stage='private_sent'`, клієнт не відповів 6h+, Meta 24h-вікно відкрите, не opt-out
- Шле текст з `drip_reminder_6h_text` через SendPulse API
- `drip_reminder_6h_sent=True` щоб не дублювати

**Stream 2 — Telegram-алерт оператору 2h (`drip_operator_alert_enabled`):**
- Фільтри: клієнт відповів (`customer_replied`), оператор не підключився 2h+, `sp_first_reply_at` порожнє
- Loud Telegram-алерт у менеджерську групу
- `drip_followup_24h_sent=True` (reuse field як maker)

**Stream 3 — Booking reminder 3d (`drip_booking_3d_enabled`):**
- Фільтри: `sp_funnel_stage='lead_created'`, `sp_lead_id` не won, не opt-out, останнє повідомлення 3d+ тому
- Шле текст з `drip_booking_3d_text`
- `drip_booking_3d_sent=True`

**Opt-out логіка:**
- Клієнт пише STOP / "не писати" / unsubscribe / відписатись → `_check_drip_stop_keyword()` ставить `drip_stop_requested=True`
- Всі drip потоки skip таких клієнтів

**Safety gates (`_can_send_drip_message`):**
- `drip_stop_requested=False`
- `stage != 'close'`
- `sp_is_comment=False` (коменти не сильно drip)
- Meta 24h-вікно відкрите

**Нові поля `sendpulse.connect`:**
- `drip_reminder_6h_sent` (Boolean)
- `drip_followup_24h_sent` (Boolean)
- `drip_booking_3d_sent` (Boolean)
- `drip_stop_requested` (Boolean)

**Нові cron:**
- `ir_cron_sendpulse_drip_followups` (1h interval)

**Settings UI:**
- Секція "V2 Automation — Sprint 3 / Drip campaigns (F2)" з master switch + per-stream toggles + custom texts

Master switch `drip_enabled` = False за замовчуванням — safe rollout. Кожен stream можна окремо включити/виключити для поступового roll-out.

---

## [2026-04-20] — v17.0.5.2

### Fix — widget="priority" on Integer field

Симптом: OWL error `Array.from requires an array-like object - not null` при відкритті `SendPulse → FAQ Entries`. Root cause: widget expected Selection options, але `priority` у `sendpulse.faq.entry` — Integer. Прибрав widget, лишив plain Integer input.

---

## [2026-04-20] — v17.0.5.1

### Sprint 2 F3 — Bot-wizard ідентифікації клієнтів

**Що робить:** коли прийшов webhook від невідомого контакту (без `res.partner`) — бот автоматично запитує email через SendPulse → на наступний inbound парсить email regex-ом → створює партнера → переводить у нормальний queue.

**Нова stage:** `identifying` (між `new` і `in_progress` у state machine).

**Нові поля `sendpulse.connect`:**
- `id_step` (Selection: `ask_email` / `ask_email_retry` / `done` / `gave_up`)
- `id_attempts` (Integer)

**Методи:**
- `_try_start_identification()` — викликається для brand-new connect з `partner=None`:
  - Перевіряє `bot_identification_enabled` + service в allowed list
  - Надсилає `_ID_ASK_EMAIL_FIRST` через `send_message_to_sendpulse`
  - Виставляє `stage='identifying'`, `id_step='ask_email'`, `id_attempts=1`
  - Повертає True → caller skip-ає normal flow (no auto-greeting, no operator notify)
- `_try_advance_identification(inbound_text)` — на наступний inbound коли `stage=identifying`:
  - Regex extract email з тексту
  - Match → create/link `res.partner`, send `_ID_THANKS`, `stage=new_message`, `id_step=done`
  - Нема → send `_ID_ASK_EMAIL_RETRY`, `id_attempts+=1`
  - Attempts > max → send `_ID_GAVE_UP`, `stage=new_message`, `id_step=gave_up` (до оператора)

**Еlig-сервіси:** telegram, instagram, messenger, whatsapp, viber (ті де бот може вільно писати без 24h обмежень при першому звернутті).

**Settings:**
- `bot_identification_enabled` (default False)
- `bot_identification_max_attempts` (default 3)

**Flow приклад:**
```
Client (Telegram): "Яка ціна?"
  [partner=None, bot_id_enabled=True, service=telegram → start flow]
Bot: "Вітаємо! 👋 Підкажіть email — надішлемо деталі 🏕️"
  [stage='identifying', id_step='ask_email']

Client: "mama@gmail.com"
  [email regex match → create res.partner]
Bot: "Дякуємо! 🙂 Записали. Менеджер зв'яжеться."
  [partner_id set, stage='new_message', id_step='done']
  [оператор бачить розмову у черзі як нормально]
```

**Fallback:**
- Якщо клієнт пише щось не-email 3 рази → `_ID_GAVE_UP` + передача оператору
- RAG FAQ auto-answer (F1) **вимкнено** поки `stage=identifying` — не плутаємо клієнта

---

## [2026-04-20] — v17.0.5.0

### Sprint 2 TZ v2.0 — F1 RAG FAQ auto-answer

Найбільша фіча V2. Коли клієнт пише питання у приват (не comment), модуль через Anthropic Claude автоматично шукає match у FAQ базі і відповідає персоналізовано — без втягування оператора.

**Модель `sendpulse.faq.entry`** (нова):
- Поля: `name`, `question`, `answer`, `tags`, `priority`, `active`, `hit_count`, `last_used_at`
- Tree/form/search views у menu «**SendPulse → FAQ Entries (RAG)**»
- Access: officer може CRUD (додати/редагувати FAQ), admin — повний
- Ordering: priority desc → hit_count desc
- Дія «Тест match» на формі (stub, TODO wizard)

**Seed data (10 стартових FAQ):**
- Ціна табору, Дати заїздів, З якого віку беруть дітей
- Що брати у табір, Харчування, Безпека
- Де знаходиться, Телефони дітям, Туга за домом, Як забронювати

**Метод `_rag_answer_question(question_text, contact_name)`** на `sendpulse.connect`:
- Бере всі активні FAQ → формує prompt для Claude
- Claude обирає best match (або NO_MATCH), генерує персоналізовану відповідь, дає confidence 0-1
- Повертає dict `{matched, faq_id, confidence, answer, reason}`
- Auto-increment `hit_count` + `last_used_at` при використанні FAQ
- In-context retrieval — НЕ embedding-based (простіше, достатньо для <100 FAQ)
- Один API call замість embed+retrieve+generate
- Cost: ~$0.001/питання на Claude Haiku (1000 input + 200 output токенів)

**Helper `_try_rag_auto_answer(question_text)`** gating logic:
- Перевіряє `rag_auto_answer_enabled` + `rag_auto_confidence_threshold`
- Rate-limit: не відповідає автоматично частіше ніж 1 раз/годину для тієї ж розмови
- При match + high confidence → `send_message_to_sendpulse` + системна нотатка у Discuss з маркером 🤖
- Зберігає `rag_auto_answered_at` + `rag_last_faq_id` на connect
- Transparent fallback — оператор бачить у Discuss що саме було автоматично відповідено

**Інтеграція у `_process_inbound`:**
- Тригер: `last_message` не порожній, `sp_is_comment=False`, існуючий connect
- Викликається після `connect.write(update_vals)`, перед notification операторів
- Silent fallback: якщо RAG не знаходить match → flow продовжується як раніше (operator queue)

**Settings:**
- `rag_auto_answer_enabled` (default False, safe rollout)
- `rag_auto_confidence_threshold` (default 0.85)

**Нові поля на `sendpulse.connect`:**
- `rag_auto_answered_at` (Datetime)
- `rag_last_faq_id` (M2O sendpulse.faq.entry)

**Нові поля у ir.config_parameter:**
- `odoo_chatwoot_connector.rag_auto_answer_enabled`
- `odoo_chatwoot_connector.rag_auto_confidence_threshold`

**Security:**
- 2 нові ACL rows для `sendpulse.faq.entry`

**Як активувати:**
1. Settings → SendPulse → V2 Automation Sprint 2 → ☑ RAG FAQ auto-answer
2. (Опційно) понизити threshold з 0.85 до 0.75 для тестування
3. Додати FAQ у меню **SendPulse → FAQ Entries** (10 seed вже є)
4. Написати на прод-бот типове питання → перевірити що 🤖 відповідь пройшла

---

## [2026-04-20] — v17.0.4.0

### Sprint 1 TZ v2.0 — 5 automation features

**F4. Auto-create `crm.lead` on funnel transition**

Коли клієнт вперше відповідає у приват (`sp_funnel_stage` → `customer_replied`), модуль автоматично створює `crm.lead`:
- Зв'язок через `sp_lead_id` (M2O вже існував)
- Ідемпотентно — повторний виклик повертає існуючий лід
- Routing sales team з Settings (`auto_create_lead_team_id`) або дефолтна команда компанії
- Lead name: `[Service] Contact name — Category`
- Description: контекст розмови + останні 5 повідомлень + bot-змінні
- Системна нотатка у Discuss-канал з клікабельним лінком на лід

Settings: `auto_create_lead_enabled` (default False, safe opt-in), `auto_create_lead_team_id`.

**F5. Auto-close inactive conversations**

Щоденний cron закриває розмови де клієнт не писав N днів:
- Фільтри: `stage ∈ {in_progress, new_message}`, `last_message_date < threshold`
- Не чіпає розмови з активним opportunity у CRM (не валідний `sp_lead_id`)
- Опційний goodbye message — шлеться тільки якщо Meta 24h-вікно відкрите і не comment-розмова

Settings: `auto_close_inactive_enabled`, `auto_close_inactive_days` (default 7), `auto_close_goodbye_text`.

**F6. Long-lived FB token auto-refresh**

Weekly cron обмінює short-lived Page Tokens на long-lived через `/oauth/access_token?grant_type=fb_exchange_token`:
- Тригер: `days_left < token_refresh_threshold_days`
- Потребує `fb_app_id` + `fb_app_secret` у Settings
- При успіху — оновлює `access_token` у `sendpulse.facebook.page` + Telegram silent alert
- При невдачі — loud Telegram alert з вимогою ручної регенерації
- Фоллбек для Pages без days_left (коли debug_token не доступний) — skip

Settings: `auto_refresh_tokens_enabled`, `token_refresh_threshold_days` (default 14).

**F7. Bulk-archive old comment records**

Monthly cron soft-archive (`active=False`) для `sp_is_comment=True` записів у stage=close старших за N днів:
- Запис залишається у БД для аудиту, але ховається з default views
- Нове поле `active` (default True, indexed) додано на `sendpulse.connect`

Settings: `auto_archive_comments_enabled` (default False), `auto_archive_comments_days` (default 30).

**F8. Weekly Telegram funnel report**

Понеділок 09:00 UTC — зводка за минулий тиждень у Telegram-групу менеджерів:
- Всього розмов: direct vs comments
- Розподіл категорій коментарів (LLM-класифікація)
- Funnel: comment_only → private_sent → customer_replied → operator_engaged → lead_created → closed_won/lost
- SLA: медіана часу до першої відповіді (хв)
- Кількість CRM лідів створено
- ⚠️ Alerts: Page Tokens з проблемним статусом

Settings: `weekly_report_enabled`. Потребує увімкнених Telegram-алертів.

### Нові cron

| ID | Interval | Метод |
|---|---|---|
| `ir_cron_sendpulse_auto_close_inactive` | 1d | `cron_auto_close_inactive` |
| `ir_cron_sendpulse_archive_old_comments` | 30d | `cron_archive_old_comment_records` |
| `ir_cron_sendpulse_weekly_report` | 7d | `cron_weekly_telegram_report` |
| `ir_cron_sendpulse_refresh_tokens` | 7d | `cron_refresh_fb_tokens` |

### Нова колонка БД

- `sendpulse_connect.active` — Boolean, default True, indexed

### Settings UI

Додана секція «V2 Automation — Sprint 1» з 8 новими полями. Всі features — behind toggle, default False (safe rollout).

---

## [2026-04-20] — v17.0.3.7.1

### Race condition fix — дублікати `sendpulse.connect` при конкурентних webhook-ах

**Симптом:** два webhook-и від SendPulse за одного контакту приходили з інтервалом ~1 секунда (зазвичай `new_subscriber` / `open_chat` + `incoming_message`). Обидва робили `search()` і не знаходили одне одного (не було commit у першого) → обидва робили `create()` → два дублікати `sendpulse.connect` з двома окремими `discuss.channel`. На проді на момент фіксу — **14 пар дублів** за 4 дні.

**Фікс:** `pg_advisory_xact_lock(hash(contact_id|service), KEY)` на початку `_process_inbound` (після ідентифікації партнера, до `search`/`create`). Другий webhook чекає commit першого, тоді бачить створений запис і оновлює його замість створення дублю. Авто-привітання теж не дублюється бо `is_brand_new=False` у другого.

Аналогічний lock додано у `_process_comment_event` на `comment_id` — SendPulse іноді ретраїть webhook-и коментарів, без lock-у дві дедуплікації проходили б одночасно.

**Cleanup existing duplicates:** всі 14 пар merged через odoo shell script. Повідомлення (`mail_message.res_id`) перенесено у keeper-канал, channel members переміщені, метадата об'єднана (`last_message_date`, `sp_first_inbound_at`), donor-канал видалено. Залишилось **0** дублів.

### Технічні деталі

```python
_SENDPULSE_INBOUND_LOCK_KEY2 = 71234

# У _process_inbound:
lock_key1 = int(
    hashlib.md5(f'{contact_id}|{service}'.encode('utf-8')).hexdigest()[:8], 16
) & 0x7FFFFFFF
self.env.cr.execute(
    'SELECT pg_advisory_xact_lock(%s, %s)',
    (lock_key1, _SENDPULSE_INBOUND_LOCK_KEY2),
)
```

Lock автоматично звільняється при commit/rollback транзакції (xact-variant). Не блокує різних контактів.

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

Додано поля у форму Налаштування → SendPulse Odoo для фіч, які з'явилися у попередніх 3.2.x–3.6.1 релізах але залишилися без UI (конфігурувалися лише через `ir.config_parameter`):

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

Новий cron `SendPulse Odoo: Перевірка FB Page Access Token` (раз на 7 днів):
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

**Нові поля Налаштувань (Налаштування → SendPulse Odoo → Відповіді на коментарі):**
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
