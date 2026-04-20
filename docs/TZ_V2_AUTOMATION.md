# TZ v2.0 — SendPulse Odo Automation

**Статус:** 📝 Draft
**Дата створення:** 2026-04-20
**Попередній TZ:** [TZ_COMMENT_AUTOREPLY.md](TZ_COMMENT_AUTOREPLY.md) — ✅ **виконаний** (v17.0.3.7.1, 2026-04-20)
**Umbrella:** [TZ.md](TZ.md)
**Базова версія модуля:** v17.0.3.7.1

---

## 0. Preamble

### 0.1 Чому v2.0

V1 (`TZ_COMMENT_AUTOREPLY`) зняв **реактивну ручну роботу з коментарями**: публічна + приватна відповідь, LLM-класифікація, Telegram-ескалація. Цього достатньо для того щоб **не губити ліди** під постами.

**Але** більшість ручної роботи досі залишилась:
- Менеджери відповідають на ті ж 40 повторюваних питань у приваті
- Клієнти пропадають без напоминання («розмова зависла»)
- Ліди губляться бо `crm.lead` створюється вручну
- Менеджмент не бачить воронку — dashboard ніхто не відкриває
- Токени експіряються тихо, потребують ручної ротації

V2 — про **проактивну автоматизацію** того що можна автоматизувати без втрати якості.

### 0.2 Попередній TZ (v1.4) — стан закриття

На 2026-04-20 всі 10/10 пунктів Definition of Done виконані:
- ✅ F1-F7 (detection, fields, public reply, private reply, dedup, notification, settings)
- ✅ Audit log у ir.logging
- ✅ Funnel metrics
- ✅ Retry + Telegram alerts

Знятий блокер Meta App Review — Advanced Access approved, 11 Pages синхронізовано з безстроковими Page Tokens. Єдине документоване обмеження: **Meta не підтримує `/private_replies` під FB Reels** (100/33 Unsupported post request) — це Meta-side, не наш баг.

---

## 1. Мета V2

**Зменшити навантаження на менеджерів на 50-70%** за рахунок автоматизації повторюваних дій + збільшити visibility воронки без додаткового людського зусилля.

### 1.1 Key success metrics

| Метрика | Baseline (v1.4) | Target (v2.0) |
|---|---|---|
| Середній час відповіді клієнту | 30 хв | < 1 хв (FAQ auto-answered) |
| % питань що відповів LLM без оператора | 0% | 60-70% |
| % лідів створених автоматично | 0% | 80% |
| Ручні ротації токенів | раз/місяць | 0 (auto-exchange) |
| «Зависли» розмови (> 3 дні без відповіді) | 15-20% | < 5% |
| Dashboards переглянуто/день | 0-1 | автозвіт у Telegram |

---

## 2. Scope V2 — 11 фіч

Розподіл на стрім-лінії за impact:

### 2.1 🔥 Customer-facing automation

#### F1. RAG-based FAQ auto-answer

**User story:** Як клієнт, я хочу отримати відповідь на типове питання за 10 секунд, а не чекати оператора 30 хвилин.

**Контекст:** На `campscout.eu/pitannia-batkiv` уже є 40+ структурованих FAQ з відповідями. LLM може автоматично вибрати правильний FAQ і персоналізувати відповідь замість відправки статичного шаблону.

**Технічний підхід:**

```python
# Нова модель
class SendpulseFaqEntry(models.Model):
    _name = 'sendpulse.faq.entry'
    question = fields.Text(required=True)
    answer = fields.Text(required=True)
    embedding = fields.Text()  # JSON-serialized vector
    tags = fields.Char()       # e.g. "price,dates,age"
    priority = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    hit_count = fields.Integer(default=0)
    last_used_at = fields.Datetime()

# Новий метод у sendpulse.connect
def _rag_answer_question(self, question_text, service):
    """
    1. Embed question через Anthropic або sentence-transformers
    2. Retrieve top-3 FAQ через cosine similarity
    3. Generate personalized reply через Claude з контекстом
    4. Return (answer, confidence)
    """
```

**Flow:**
```
Client sends question у DM
  → _classify_comment → 'question_*'
  → _rag_answer_question → (answer, confidence)
  ├── confidence > 0.85 → send_message_to_sendpulse + log
  │                        + set sp_funnel_stage='auto_answered'
  ├── 0.60 < conf ≤ 0.85 → show as "Suggested reply" у Discuss
  │                        (оператор approve/edit)
  └── conf ≤ 0.60        → передати оператору як зараз
```

**Acceptance criteria:**
- [ ] Модель `sendpulse.faq.entry` з UI для додавання/редагування FAQ
- [ ] Кнопка «Імпортувати з campscout.eu/pitannia-batkiv» (HTML scraper → записи)
- [ ] Embedding через Anthropic API (якщо доступне) або `sentence-transformers/all-MiniLM-L6-v2`
- [ ] Cosine similarity lookup у Python (без додаткової vector DB)
- [ ] Toggle у Settings: `rag_auto_answer_enabled`
- [ ] Confidence threshold configurable: `rag_auto_confidence_threshold` (default 0.85)
- [ ] Метрика: `hit_count` per FAQ + `last_used_at` — для аналізу покриття
- [ ] Telegram звіт щотижня: top-10 FAQ, top-10 unmatched questions
- [ ] Unit tests: cosine math, retrieval, fallback behavior

**Estimated effort:** 2 дні
**Dependencies:** Anthropic API key (вже є), Meta App approved (вже є)

---

#### F2. Drip-кампанії по `sp_funnel_stage`

**User story:** Як менеджер, я не хочу пам'ятати про 50 клієнтів що не відповіли — хочу щоб модуль сам їм нагадав або розбудив мене.

**Матриця дій:**

| Стадія | Час з останньої дії | Автоматична дія |
|---|---|---|
| `private_sent` | 6h без inbound | Нагадування клієнту: «Ви отримали наше повідомлення? Будемо раді відповісти на питання 🏕️» |
| `customer_replied` | 2h без operator_engaged | Telegram-алерт менеджеру: «Клієнт X чекає відповідь 2h» (loud) |
| `operator_engaged` | 24h silent | Follow-up клієнту: «Потрібна допомога? Ми тут щоб відповісти» |
| `lead_created` | 3 дні без payment | Reminder клієнту про бронь + knife feature (last chance) |
| `in_progress` | 7 днів silent | Auto-close + follow-up «Сподіваємося, ви зберегли нашу інформацію — пишіть як будуть питання!» |

**Технічний підхід:**

```python
@api.model
def cron_drip_followups(self):
    """Запускається 1 раз/год. Обробляє кожну стадію окремо."""
    now = fields.Datetime.now()
    # private_sent → 6h reminder
    records = self.search([
        ('sp_funnel_stage', '=', 'private_sent'),
        ('sp_first_reply_at', '=', False),  # клієнт ще не відповів
        ('sp_messenger_window_expires_at', '>', now + timedelta(hours=1)),  # вікно відкрите
        ('last_message_date', '<', now - timedelta(hours=6)),
        ('drip_reminder_6h_sent', '=', False),
    ])
    for rec in records:
        rec.send_message_to_sendpulse(DRIP_TEMPLATES['reminder_6h'].format(name=rec.name))
        rec.write({'drip_reminder_6h_sent': True})
    # ... аналогічно для інших стадій
```

**Нові поля на `sendpulse.connect`:**
- `drip_reminder_6h_sent` (Boolean)
- `drip_followup_24h_sent` (Boolean)
- `drip_booking_3d_sent` (Boolean)

**Acceptance criteria:**
- [ ] Cron `cron_drip_followups` (1h interval)
- [ ] Templates у `ir.config_parameter`: `drip_reminder_6h_text`, `drip_followup_24h_text`, etc.
- [ ] Per-service enable (Telegram — так, IG DM — тільки якщо 24h вікно відкрите)
- [ ] Respect `sp_messenger_window_expires_at` — не шлемо якщо Meta заблокувало
- [ ] Метрика: скільки drip-messages відправлено, скільки отримало відповідь
- [ ] Opt-out: якщо клієнт написав `STOP` або `не писати` → автоматично `stop_drip=True`

**Estimated effort:** 1.5 дні
**Dependencies:** Нема

---

#### F3. Бот-wizard ідентифікації клієнта

**User story:** Як оператор, я не хочу руками питати «як вас звати, залиште email» — хочу щоб бот це робив автоматично і заповнив картку партнера.

**Контекст:** Зараз новий клієнт пише «Яка ціна?» — оператор відкриває wizard → руками заповнює email/phone → прив'язує партнера. Це 2-3 хвилини на кожну нову розмову.

**Технічний підхід:**

```python
# Нова стадія
STAGE_SELECTION.append(('identifying', 'Ідентифікація'))

# У _process_inbound якщо partner is None:
# 1. Створити sendpulse.connect з stage='identifying'
# 2. Відправити клієнту: «Привіт! 👋 Як до вас можна звертатись? Поділіться ім'ям — і ми зразу підберемо табір»
# 3. На наступний inbound — парсимо ім'я/email (regex)
# 4. Якщо email → GET partner by email → match
# 5. Якщо не знайшли → запитати «email?» → створити партнера
# 6. Коли зібрали мінімум (name + email OR phone) → move to stage='new'
```

**State machine identification flow:**

```
(new inbound without partner)
  → identifying, ask_name
  → (inbound with name parsed)
  → identifying, ask_email
  → (inbound with email)
  ├── email matches res.partner → link, stage=new_message
  └── no match → create partner, stage=new_message
```

**Acceptance criteria:**
- [ ] Selection stage `identifying` додано
- [ ] Поля tracking: `id_step` (ask_name/ask_email/ask_phone/done)
- [ ] Парсер name з повідомлення (naive: first 50 chars, strip emoji)
- [ ] Парсер email (regex standard)
- [ ] Парсер phone (E.164 + UA/PL formats)
- [ ] Toggle у Settings: `bot_identification_enabled` (default False для safe opt-in)
- [ ] Fallback: якщо клієнт 3 рази не дав email → move до operator як `new`
- [ ] Метрика: % ідентифікованих автоматично vs через operator wizard

**Estimated effort:** 2 дні
**Dependencies:** Нема

---

### 2.2 📊 Operational automation

#### F4. Auto-create `crm.lead` з funnel

**User story:** Як sales manager, я хочу бачити всіх потенційних клієнтів у `crm.lead` автоматично — не ходити по Discuss-каналах.

**Триггер:** Коли `sp_funnel_stage` переходить у `customer_replied` **І** (`sp_comment_category IN question_*` або `is_unidentified = False`).

**Технічний підхід:**

```python
def _auto_create_crm_lead(self):
    """Створює crm.lead зв'язаний з цим sendpulse.connect."""
    self.ensure_one()
    if self.sp_lead_id:
        return self.sp_lead_id  # already exists
    team = self._get_sales_team_for_service()  # routing за service або bot_id
    lead_vals = {
        'name': f"[{self.service.upper()}] {self.name}",
        'partner_id': self.partner_id.id if self.partner_id else False,
        'email_from': self.partner_id.email if self.partner_id else self.unidentified_email,
        'phone': self.partner_id.phone if self.partner_id else self.unidentified_phone,
        'source_id': self.source_id.id if self.source_id else False,
        'team_id': team.id if team else False,
        'description': self._format_lead_description(),  # text із 5 останніх повідомлень
        'user_id': self._choose_assignee(team).id if team else False,  # round-robin
    }
    lead = self.env['crm.lead'].create(lead_vals)
    self.write({'sp_lead_id': lead.id, 'sp_funnel_stage': 'lead_created'})
    return lead
```

**Acceptance criteria:**
- [ ] Triggered у `_process_inbound` коли funnel transitions to `customer_replied`
- [ ] Triggered manually через `action_create_lead` (кнопка на form view) для edge cases
- [ ] Sales team routing: per-service + per-bot_id у Settings
- [ ] Round-robin assignment у вибраній team
- [ ] Lead description auto-filled з last 5 messages
- [ ] Bidirectional link: `sendpulse.connect.sp_lead_id` ↔ `crm.lead.sendpulse_connect_ids` (one2many)
- [ ] Вкладка у `crm.lead` form з Discuss-каналом вбудованою

**Estimated effort:** 3 години
**Dependencies:** Налаштовані `crm.team`

---

#### F5. Auto-close inactive conversations

**User story:** Як менеджер, я не хочу бачити у черзі розмови від 2 місяців тому що ніхто вже не чекає відповіді.

**Технічний підхід:**

```python
@api.model
def cron_auto_close_inactive(self):
    """Щоденно. Закриває розмови inactive 7+ днів."""
    threshold = fields.Datetime.now() - timedelta(days=7)
    records = self.search([
        ('stage', 'in', ['in_progress', 'new_message']),
        ('last_message_date', '<', threshold),
        # але не чіпаємо ті де клієнт щойно написав
        ('sp_first_inbound_at', '<', threshold),
    ])
    for rec in records:
        # Опційно — send goodbye message
        if rec.service_allows_free_messaging():
            rec.send_message_to_sendpulse(
                "Сподіваємося, ви знайшли потрібну інформацію! "
                "Якщо будуть питання — пишіть, ми тут 🙂"
            )
        rec.action_close()
```

**Acceptance criteria:**
- [ ] Cron `cron_auto_close_inactive` (1d interval)
- [ ] Configurable threshold: `auto_close_inactive_days` (default 7)
- [ ] Toggle: `auto_close_enabled`
- [ ] Respect 24h window (не намагається писати якщо вікно закрите)
- [ ] Goodbye message configurable
- [ ] Skip розмов з active CRM lead у stage > "Qualified" (ліди в роботі не чіпаємо)
- [ ] Audit log: скільки закрито, який reason

**Estimated effort:** 2 години
**Dependencies:** Нема

---

#### F6. Long-lived token auto-refresh

**User story:** Як адмін, я хочу щоб модуль сам продовжував FB токени — не ловити 2 AM ранкові падіння коли 60 днів минуло.

**Технічний підхід:**

Meta Graph API має endpoint `/oauth/access_token?grant_type=fb_exchange_token` — обмінює short-lived User Token на long-lived (60 днів), або long-lived на долший (іноді безстроковий для System User flow).

```python
def _exchange_token_for_long_lived(self, short_lived_token):
    """
    POST /v25.0/oauth/access_token?grant_type=fb_exchange_token
        &client_id={app_id}&client_secret={app_secret}
        &fb_exchange_token={short_lived_token}
    → long_lived_token (60 days або never-expire якщо System User flow)
    """

@api.model
def cron_refresh_tokens(self):
    """Weekly. Для кожного Page з expiry < 14д → exchange."""
    Page = self.env['sendpulse.facebook.page'].sudo()
    for page in Page.search([('active', '=', True)]):
        if not page.access_token:
            continue
        # читаємо days_left з token_status або дебаг заново
        result = self._check_single_fb_token(page.access_token, page.name)
        days_left = result.get('days_left')
        if days_left is not None and days_left < 14:
            new_token = self._exchange_token_for_long_lived(page.access_token)
            if new_token:
                page.write({'access_token': new_token})
                self._notify_telegram(
                    f'🔄 Page Token refreshed for {page.name} — new expiry {days_left_after_refresh}d',
                    silent=True,
                )
```

**Acceptance criteria:**
- [ ] Метод `_exchange_token_for_long_lived(token)` з error handling
- [ ] Cron `cron_refresh_tokens` (7d interval, run after `cron_check_fb_token_expiry`)
- [ ] Threshold configurable: `token_refresh_threshold_days` (default 14)
- [ ] Toggle: `auto_refresh_tokens_enabled`
- [ ] Telegram alert на кожен успішний exchange (silent)
- [ ] Telegram loud-alert якщо exchange **не вдалось** — вимагає ручної дії
- [ ] Fallback — якщо exchange provides only 60d token (не never-expire), cron продовжує щотижня

**Estimated effort:** 4 години
**Dependencies:** `fb_app_id` + `fb_app_secret` у Settings (зараз pending)

---

#### F7. Bulk-close старих closed коментарів

**User story:** Як менеджер, я не хочу щоб БД тягнула 10k коментарних `sendpulse.connect` записів що ніколи не будуть активовані.

**Технічний підхід:**

Soft-archive через `active=False` — не видаляємо (зберігаємо для аудиту), але приховуємо з default views.

```python
@api.model
def cron_archive_old_comment_records(self):
    """Monthly. Archive comment-records що закриті 30+ днів."""
    threshold = fields.Datetime.now() - timedelta(days=30)
    records = self.search([
        ('sp_is_comment', '=', True),
        ('stage', '=', 'close'),
        ('write_date', '<', threshold),
    ])
    records.write({'active': False})
```

**Додати `active=True` default поле на `sendpulse.connect`** (зараз його нема — завжди active).

**Acceptance criteria:**
- [ ] Поле `active` додано з `default=True`
- [ ] Default search domain `('active', '=', True)` у form/list
- [ ] Cron monthly archiver
- [ ] Кнопка «Архівовані» у menu — показує inactive
- [ ] Unarchive — reveal кнопка на form якщо admin

**Estimated effort:** 2 години
**Dependencies:** Нема

---

### 2.3 📈 Analytics automation

#### F8. Weekly funnel report у Telegram

**User story:** Як керівник, я хочу щопонеділка о 9:00 бачити у Telegram зводку за минулий тиждень без відкриття Odoo.

**Приклад повідомлення:**

```
📊 Минулий тиждень (13–19 квітня)

Webhook events: 312
├─ Direct DMs: 187 (60%)
└─ Comments: 125 (40%)

Comments класифіковано:
💰 question_price: 42
📅 question_dates: 28
👶 question_age: 18
❓ question_general: 22
🙏 thanks: 9
🚨 complaint: 2 (ескалавано)
🚫 spam: 4 (автоприховано)

Funnel:
47 коментарів → 38 private → 24 replied (63%)
7 лідів створено → 3 замовлення (43% conversion)

Performance:
⏱ Avg response time: 12 хв (SLA < 15 хв: 78%)
🏆 Best operator: Юрій (14 чатів, avg 8 хв)

Alerts:
⚠️ FB Token CampScout — 58 днів залишилось (auto-refresh scheduled)
⏳ 3 чати з 24h вікном що закрилось без відповіді
```

**Технічний підхід:**

```python
@api.model
def cron_weekly_telegram_report(self):
    """Понеділок 09:00 UTC."""
    week_start = fields.Datetime.now() - timedelta(days=7)
    stats = self._calculate_weekly_stats(week_start)
    message = self._format_weekly_report(stats)
    self._notify_telegram(message, silent=False)
```

**Acceptance criteria:**
- [ ] Cron `cron_weekly_telegram_report` з розкладом `0 9 * * 1` (понеділок 9:00)
- [ ] Aggregation method `_calculate_weekly_stats` — всі метрики з SQL запитів
- [ ] Template функція `_format_weekly_report` (Ukrainian + HTML)
- [ ] Toggle у Settings: `weekly_report_enabled`
- [ ] Timezone-aware (використовуємо `ir.config_parameter.timezone`)
- [ ] Graceful на відсутність Telegram config

**Estimated effort:** 4 години
**Dependencies:** `_notify_telegram` (вже є)

---

#### F9. Auto A/B тестування шаблонів публічних відповідей

**User story:** Як маркетолог, я хочу знати який з 5 шаблонів найкраще конвертує у private replies — не дивлячись у SQL.

**Технічний підхід:**

Трансформувати `_COMMENT_PUBLIC_TEMPLATES` з Python-списка у модель з метриками.

```python
class SendpulsePublicTemplate(models.Model):
    _name = 'sendpulse.public.template'
    name = fields.Char(required=True)
    text = fields.Text(required=True)
    active = fields.Boolean(default=True)
    use_count = fields.Integer(default=0)
    private_reply_sent_count = fields.Integer(default=0)  # скільки разів після цього private теж пішло
    customer_replied_count = fields.Integer(default=0)    # скільки клієнтів після цього написали у приват
    conversion_rate = fields.Float(compute='_compute_conversion_rate', store=True)

    @api.depends('use_count', 'customer_replied_count')
    def _compute_conversion_rate(self):
        for rec in self:
            rec.conversion_rate = (rec.customer_replied_count / rec.use_count * 100) if rec.use_count else 0.0
```

**Rotation algorithm:**
```python
# замість [count % 5] — weighted random
def _pick_template(self, post_id):
    templates = SendpulsePublicTemplate.search([('active', '=', True)])
    # Epsilon-greedy: 80% найкращий (за conversion), 20% random explore
    if random() < 0.2:
        return random.choice(templates)
    return templates.sorted(key='conversion_rate', reverse=True)[0]
```

**Acceptance criteria:**
- [ ] Модель `sendpulse.public.template` з UI (menu under SendPulse)
- [ ] Migration: seed з поточних 5 шаблонів + REPEAT_TEMPLATE
- [ ] Tracking: `use_count`, `customer_replied_count` оновлюються у `_process_inbound` при переході у `customer_replied`
- [ ] Stored `conversion_rate` computed field
- [ ] Auto-disable якщо `conversion_rate < 40% середнього` після мінімум 50 використань
- [ ] Dashboard graph view з conversion_rate per template
- [ ] Expose у Weekly Telegram Report (top-3 + worst-1)

**Estimated effort:** 1 день
**Dependencies:** F8 (для reporting integration)

---

### 2.4 🛠 Operator productivity

#### F10. Suggested reply (LLM draft) у Discuss panel

**User story:** Як оператор, я відкриваю розмову і бачу збоку 3 варіанти відповіді від LLM — натискаю «Use», правлю якщо треба, відправляю. Економія 3-5x часу.

**Технічний підхід:**

OWL-компонент у `sendpulse_info_panel` отримує контекст:
- Останні 5 повідомлень розмови
- Профіль клієнта (child_name, booking_email)
- FAQ-тегний контекст з `_classify_comment`

Робить RPC на `sendpulse.connect._generate_reply_suggestions(connect_id)`:

```python
def _generate_reply_suggestions(self, count=3):
    """Повертає N draft reply options через Claude."""
    self.ensure_one()
    context = self._build_reply_context()
    prompt = f"""
    Контекст розмови з клієнтом CampScout:
    {context}

    Стиль: коротко, по-людському, без формальності, з емодзі помірно.
    Згенеруй {count} різних варіантів наступного повідомлення оператора.
    Формат: JSON список рядків.
    """
    response = self._call_anthropic(prompt, max_tokens=500)
    return json.loads(response)
```

**Frontend:**
```js
// sendpulse_info_panel.js
const suggestions = await rpc('/web/dataset/call_kw', {
    model: 'sendpulse.connect', method: '_generate_reply_suggestions',
    args: [this.props.connectId, 3], kwargs: {}
});
// Render 3 buttons, on click fill Discuss composer input
```

**Acceptance criteria:**
- [ ] RPC endpoint `_generate_reply_suggestions`
- [ ] OWL панель відображає 3 variants як clickable buttons
- [ ] Click → fill composer input (не автоматично send)
- [ ] Loading state + error handling (graceful якщо Claude недоступний)
- [ ] Toggle у Settings: `suggested_reply_enabled`
- [ ] Кеш variants на 5 хв (щоб не пересилати на refresh)
- [ ] Cost control: max 100 generations/day per operator

**Estimated effort:** 1 день
**Dependencies:** Anthropic key

---

#### F11. Auto-translate для operators

**User story:** Як польський оператор, я бачу текст клієнта українською — хочу переклад під рукою щоб не відкривати Google Translate.

**Технічний підхід:**

```python
def _detect_and_translate(self, text, target_lang='pl'):
    """
    1. Language detection через Claude (one-shot)
    2. Якщо source != target → translate
    3. Cache результату per-message
    """
```

**Frontend:** Під кожним message у Discuss (для incoming) показується `🇵🇱 Переклад» collapsible section — клік → показати. API call робиться on-demand.

**Acceptance criteria:**
- [ ] RPC `_translate_message(message_id, target_lang)`
- [ ] OWL hook у mail message renderer (patch)
- [ ] Detect source lang automatically
- [ ] Only show «Переклад» якщо detected_lang != operator_lang
- [ ] Operator lang з `res.users.lang` (Odoo built-in)
- [ ] Cache у field `mail.message.translation_pl` / `translation_uk` / ... (соціальний перехід)
- [ ] Toggle у User Preferences: «Auto-translate SendPulse messages»

**Estimated effort:** 1.5 дні
**Dependencies:** Anthropic key

---

## 3. Priorities / Execution plan

### 3.1 Sprint 1 (тиждень 1) — quick wins

| Фіча | Effort | Impact | Rationale |
|---|---|---|---|
| F4 Auto-create `crm.lead` | 3h | 🟢 High | Ліди перестають губитися — одразу більше замовлень |
| F5 Auto-close inactive | 2h | 🟡 Medium | Чиста черга для менеджерів |
| F6 Long-lived token refresh | 4h | 🔴 Critical | Знімає ризик мовчазних падінь |
| F7 Bulk-close старих коментів | 2h | 🟡 Medium | DB гігієна |
| F8 Weekly Telegram report | 4h | 🟢 High | Visibility для керівництва |

**Total Sprint 1: ~15h = 2 дні.** Mini-release v17.0.4.0.

### 3.2 Sprint 2 (тиждень 2) — customer-facing

| Фіча | Effort | Impact |
|---|---|---|
| F1 RAG FAQ auto-answer | 2 дні | 🟢🟢 Very High |
| F3 Бот-wizard ідентифікації | 2 дні | 🟢 High |

**Total Sprint 2: ~4 дні.** Major release v17.0.5.0.

### 3.3 Sprint 3 (тиждень 3) — operator UX

| Фіча | Effort | Impact |
|---|---|---|
| F10 Suggested reply | 1 день | 🟢 High |
| F2 Drip-кампанії | 1.5 дні | 🟢 High |
| F9 Auto A/B templates | 1 день | 🟡 Medium |
| F11 Auto-translate | 1.5 дні | 🟡 Medium |

**Total Sprint 3: ~5 днів.** Major release v17.0.6.0.

---

## 4. Non-goals (що **не** у v2.0)

- ❌ Voice messages transcription — Anthropic не має Speech API на 2026-04, чекаємо
- ❌ Multi-tenancy (різні CampScout-equivalent клієнти на одному Odoo) — окремий TZ v3
- ❌ Replacement ChatWoot або SendPulse — модуль залишається bridge-ом, не own-stack
- ❌ Real-time live chat на campscout.eu — через окремий `website_livechat` або аналог
- ❌ Власний mobile app для операторів — Odoo Enterprise mobile достатньо
- ❌ Payment collection у чаті — через окремий PSP-модуль

---

## 5. Dependencies & prerequisites

### 5.1 Вже наявне

- ✅ LLM-класифікатор (Anthropic Claude Haiku)
- ✅ Multi-page FB з безстроковими tokens
- ✅ Telegram-алерти (`@csodooalerts_bot`)
- ✅ Funnel metrics + SLA fields
- ✅ Meta App Review approved

### 5.2 Потрібно отримати

- ⚠️ **FB App Secret** — для F6 (token exchange) і `debug_token`. Джерело: developers.facebook.com → Campscout_odoo → Settings → Basic → App Secret (Show)
- ⚠️ **Анропік API budget** — для F10 (suggested reply може збільшити витрати ×3-5). Orientation: при 500 комтементарів/день × 3 variants × 100 токенів = $0.05/день. Безпечно.

### 5.3 Рішення що чекаємо

- **RAG source:** тільки campscout.eu/pitannia-batkiv чи додатково програми таборів, юридичні документи, FAQ блогу? — впливає на scope F1
- **Drip defaults:** які тексти напоминань? — впливає на F2 templates
- **Sales team routing:** як розподіляємо ліди — за `service` (Telegram→Ira, IG→Юрій) чи round-robin? — впливає на F4

---

## 6. Definition of Done для V2 (закриття всього TZ)

Загальна DoD — всі 11 фіч реалізовані + наступне:

- [ ] Всі фічі мають Settings toggle (щоб можна було вимкнути окремо)
- [ ] Unit tests на критичні методи (RAG retrieval, template picker, lead creation, token exchange)
- [ ] Integration tests на реальному стейджі (не тільки CampScout прод)
- [ ] README оновлений з V2-фічами
- [ ] CHANGELOG.md з розділом v17.0.4-17.0.6
- [ ] docs/CONFIGURATION.md включає нові Settings
- [ ] docs/ARCHITECTURE.md має діаграми drip-flow і RAG-flow
- [ ] Weekly Telegram report отриманий мінімум 4 рази (покриває sprint-цикл)
- [ ] Production-метрика: час відповіді < 1 хв для 60%+ питань (FAQ-auto-answer live)
- [ ] Zero ручних ротацій токенів за місяць після release

---

## 7. Success metrics revisit (на моменті закриття)

| Метрика | Target | Measurement |
|---|---|---|
| Середній час відповіді клієнту | < 1 хв (60% запитань) | `sp_first_reply_time_sec` median, filtered by `category=question_*` |
| % RAG auto-answered | 60-70% | `_rag_answer_question` hits / total questions |
| % лідів створених автоматично | 80% | `crm.lead.source` = 'sendpulse_auto' / total |
| Ручних ротацій токенів/місяць | 0 | cron logs + Telegram alerts |
| «Зависли» розмови > 3 дні | < 5% | `stage=in_progress AND last_message_date < now-3d` count |
| Weekly report delivery | 100% (4/4) | Telegram group log |

---

## 8. Ризики

| Ризик | Ймовірність | Mitigation |
|---|---|---|
| RAG hallucinates — відповідає вигаданою інформацією | High | Confidence threshold 0.85, sample review operator-ами перші 2 тижні, strict grounding prompt |
| Drip-повідомлення як spam Meta-side → Page blocked | Medium | Respect 24h window, opt-out detection, rate limit 1 drip/contact/day |
| LLM API outage ламає FAQ flow | Medium | Graceful fallback на оператора (як до V2), Telegram loud alert |
| Auto-create lead ламає sales workflow | Medium | Release з toggle `auto_create_lead_enabled`, пилотним дні з вимкненим, потім включити |
| Auto-close видалив активну розмову | Low | Respect пилотною > 7 днів, explicit goodbye message, undo button у UI |

---

## 9. Sign-off

- **Author:** Fayna Digital — Volodymyr Shevchenko
- **Date:** 2026-04-20
- **Version:** 2.0 (draft)
- **Expected release:** v17.0.4.0 (Sprint 1) — до 2026-04-27

---

*Цей документ слугує джерелом правди для V2-ітерації. Зміни scope — через явне редагування з оновленням версії (2.0 → 2.1 і т.д.) і запис у LOG.md.*
