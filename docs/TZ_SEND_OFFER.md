# ТЗ — Фіча «Wyślij ofertę»: PL-каталог через лінк (channel-independent)

**Репо:** `fayna-sendpulse-odoo` (модуль `odoo_chatwoot_connector`) · гілка `feature/send-offer-link` · Odoo 17 · LGPL-3
**Версія:** `17.0.14.10` → `17.0.14.11`
**Принцип (#BOUNDARY):** ТІЛЬКИ доповнюємо. Наявний UA-flow F13 (`_send_pdf_catalog_email` з attachment), його ідемпотентність (`sp_pdf_sent_at`/`sp_pdf_sent_to_email`), RODO-лог і RPC `send_pdf_catalog_for_channel` НЕ ламаємо. Зовнішній контракт F13 (`{'ok','error','message_id'}`) зберігається.

> Усі факти нижче звірені з кодом (grep/Read), не з пам'яті.

---

## 0. Проблема й виявлені факти

**Мета:** надсилати PL-каталог обозів 2026 як **посилання** (а не важкий ~24 МБ attachment) — і вміти це робити для **вручну створених клієнтів** (`res.partner`, `crm.lead`) БЕЗ запису `sendpulse.connect`, кнопкою «Wyślij ofertę». UA-flow F13 з каналу теж переходить на PL+лінк.

**Звірені факти (код станом на 17.0.14.10):**
1. `_send_pdf_catalog_email` — `models/sendpulse_connect.py:2954`, `ensure_one()`. Рендерить через `tpl._generate_template([self.id], ['subject','body_html','email_from'])` — тобто **прив'язано до `sendpulse.connect` як `res_id`**.
2. Шаблон `mail_template_lead_magnet_catalog` (`data/mail_template_lead_magnet.xml:7`) має `model_id ref="model_sendpulse_connect"`, `lang=uk_UA`. **Для ручного шляху запису `sendpulse.connect` немає → цей рендер непридатний.** Це головний ризик (R1).
3. Картинки: post-replace URL у `body_html` (avatar uid=6 → `_get_or_create_public_image`, logo PNG → `_get_email_logo_png_b64`), бо Gmail ріже Data URI >8 КБ. Метод сервить `/web/image/{id}/...`.
4. Attachment у F13: `lead_magnet_pdf_attachment_id` (param), додається через `email_values['attachment_ids']` (`:3061`, `:3087`).
5. `crm` **вже** в `depends` (`__manifest__.py:37`) — окремий depend не потрібен.
6. RODO `purpose` Selection (`sendpulse_privacy_consent_log.py:50`) НЕ має `offer_email` — є лише `lead_magnet_email`, `lead_magnet_sms`, `marketing_email`, `marketing_sms`, `transactional`, `other`.
7. RODO `source` Selection (`:114`) ВЖЕ має `admin_manual` — **нове значення `manual_offer` НЕ додаємо** (зайва міграція).
8. `generate_access_token()` патерн уже вживається в `mail_channel.py:239`.

---

## 1. Архітектурне рішення (обране, несуперечливе)

Виносимо **композицію+надсилання** у channel-independent метод. Найчистіше місце — `res.partner`, бо partner є носієм email і RODO-суб'єктом, і він існує в обох шляхах (у каналі через `connect.partner_id`, вручну — напряму).

**Ядро (DRY):** `res.partner._compose_and_send_offer(...)`. Рендер PL-шаблону робимо через цей же partner-record (шаблон прив'язуємо до `res.partner`), що знімає R1. Лінк передаємо через context, у тіло — post-replace маркера (надійніше за context-плейсхолдер, узгоджено з наявним стилем replace avatar/logo).

**Обидва шляхи кличуть ядро:**
- **F13 (канал):** `_send_pdf_catalog_email` лишається обгорткою — тримає свою idempotency (`sp_pdf_sent_at`), резолвить partner, делегує в `partner._compose_and_send_offer(connect=self, ...)`.
- **Ручний:** `action_send_offer_email` на `res.partner` і `crm.lead` → `partner._compose_and_send_offer(source='admin_manual')`.

**Чому не AbstractModel-mixin / не `@api.model` на connect:** mixin — надлишково для 2 викликів; метод на connect знову тягне залежність від каналу. Partner-метод — мінімальне чисте рішення.

---

## 2. Конфіг (ir.config_parameter, config-driven, без хардкоду)

| Параметр | Призначення | Дефолт |
|---|---|---|
| `odoo_chatwoot_connector.offer_pdf_attachment_id` | id `ir.attachment` PL-каталогу (~24 МБ) | `''` |
| `odoo_chatwoot_connector.offer_email_lang` | мова листа оферти | `pl_PL` |
| `odoo_chatwoot_connector.lead_magnet_enabled` | наявний gate (reuse) | `False` |
| `odoo_chatwoot_connector.consent_enforcement_enabled` | наявний RODO-gate (reuse) | `True` |

- URL завантаження будуємо **в коді** (не в шаблоні):
  `{base_url}/web/content/{att.id}?download=true&access_token={att.access_token}`
  де `base_url = ICP.get_param('web.base.url').rstrip('/')`.
- `access_token`: генерувати **лише якщо порожній** — `att.access_token or att.generate_access_token()[0]` (інакше старі лінки в надісланих листах протухнуть; патерн `mail_channel.py:239`). Токен НЕ зберігаємо в param — читаємо з самого attachment, ідемпотентно.
- `lead_magnet_pdf_attachment_id` (UA, attachment-режим) лишається незмінним для зворотної сумісності.
- Опційно: поле в `res.config.settings` (`Many2one ir.attachment`, `config_parameter='...offer_pdf_attachment_id'`) для зручного вводу — узгоджено зі стилем `res_config_settings.py`.

---

## 3. Моделі / методи

### 3.1 `models/res_partner.py` — НОВЕ ядро (DRY)

```python
def _compose_and_send_offer(self, to_email=None, connect=False, source='admin_manual',
                            consent_msg=False, name=False):
    """Channel-independent: композиція+надсилання PL-листа оферти з лінком.
    Викликають: F13 (connect=self) і ручні кнопки partner/crm.lead.
    Повертає {'ok','error','message_id'}."""
    self.ensure_one()
```

Логіка (адаптовано з `sendpulse_connect._send_pdf_catalog_email`):
1. Gate `lead_magnet_enabled` → `{'ok':False,'error':'disabled'}`.
2. Резолв `to_email = (to_email or self.email).strip()`; порожній → `no_email`.
3. **RODO enforcement** (`consent_enforcement_enabled`): останній `consent.log` по `purpose='lead_magnet_email'`+`email` → якщо `consent_given=False` → `consent_withdrawn`.
4. Резолв attachment з `offer_pdf_attachment_id` → `.exists()`/`.datas`; інакше `no_offer_attachment`. Побудова `download_url` (§2, токен лише якщо порожній).
5. Картинки: **повторно використати** `_get_or_create_public_image` / `_get_email_logo_png_b64`. **Перенести ці два хелпери з `sendpulse_connect.py` у `res.partner`** (вони channel-незалежні — залежать від company/signer uid=6, не від каналу). grep на інші виклики ПЕРЕД переносом; де лишилось — кликати `self.env['res.partner']`-версію, копій не плодити.
6. Рендер `mail_template_offer_catalog_pl` (model=`res.partner`) через `tpl._generate_template([self.id], ['subject','body_html','email_from'])`; post-replace avatar/logo URL (як у F13) + post-replace маркера `{{DOWNLOAD_URL}}` → `download_url`.
7. `send_mail(self.id, force_send=True, email_values={'email_to':..., 'body_html':...})` — **БЕЗ `attachment_ids`**.
8. **RODO** `record_consent(purpose='lead_magnet_email', channel='email', partner_id=self.id, connect_id=connect.id if connect else False, message_id=consent_msg, email=to_email.lower(), consent_given=True, source=source, legal_basis='consent')`.
9. `_logger.info(...)`; return `{'ok':True,'error':None,'message_id':<mail_id>}`.

> **Чому `purpose='lead_magnet_email'` (а не новий `offer_email`):** це та сама дія (надсилання PDF-каталогу на email), той самий enforcement-домен; новий purpose вимагав би міграції Selection + дублював би семантику. Чистота audit зберігається через `source` (`sendpulse_chat` vs `admin_manual`), яке вже є.

### 3.2 `models/res_partner.py` — UI-екшен

```python
def action_send_offer_email(self):
    self.ensure_one()
    if not self.email:
        raise UserError(_('Контакт без email — додайте email.'))
    res = self._compose_and_send_offer(source='admin_manual')
    # display_notification: success / danger за res['ok'], текст з res['error']
```

### 3.3 `models/sendpulse_connect.py` — рефактор F13 (обгортка)

`_send_pdf_catalog_email(to_email)` лишається `ensure_one`, тримає СВОЄ:
- gate, резолв email, **idempotency** (`sp_pdf_sent_at`/`sp_pdf_sent_to_email`),
- забезпечує partner: `partner = self.partner_id` → якщо порожній, **fallback на наявний inline-шлях connect** (legacy, не видаляти — анонімні чати без partner),
- делегує: `res = self.partner_id._compose_and_send_offer(to_email=to_email, connect=self, source='sendpulse_chat', consent_msg=<last incoming msg id>)`,
- після `res['ok']` пише `sp_pdf_sent_at`/`sp_pdf_sent_to_email`.

`send_pdf_catalog_for_channel` — **без змін сигнатури**. Перехід UA→PL: активним стає PL-шаблон+лінк; UA-шаблон `mail_template_lead_magnet_catalog` НЕ видаляємо (legacy/fallback для connect без partner).

### 3.4 `models/crm_lead.py` — НОВИЙ файл

```python
class CrmLead(models.Model):
    _inherit = 'crm.lead'
    def action_send_offer_email(self):
        self.ensure_one()
        partner = self.partner_id or self.env['res.partner'].search(
            [('email', '=', self.email_from)], limit=1)
        if not partner:
            raise UserError(_('Лід без контакту/email — створіть контакт.'))
        res = partner._compose_and_send_offer(to_email=self.email_from, source='admin_manual')
        # display_notification
```
Реєстрація: `from . import crm_lead` у `models/__init__.py`.

---

## 4. Data / Template

### 4.1 `data/mail_template_offer_catalog_pl.xml` — НОВИЙ (`noupdate="1"`)
- `id="mail_template_offer_catalog_pl"`, `model_id ref="base.model_res_partner"`, `lang` = `{{ object.lang or 'pl_PL' }}`.
- `subject` (PL): `CampScout — katalog obozów 2026 🏕️`.
- `body_html`: PL-копія наявного брендованого layout (червона смуга `#952426`, лого, гарантії організатора, підпис Volodymyr, RODO+unsubscribe-блок), АЛЕ:
  - замість блоку «у вкладенні PDF» → **CTA-кнопка** `<a href="{{DOWNLOAD_URL}}">Pobierz katalog (PDF)</a>` (маркер `{{DOWNLOAD_URL}}` post-replace у коді).
  - Зберегти маркери URL avatar (`.../res.users/6/avatar_128`) та logo (`.../res.company/1/logo`) для того ж post-replace, що у F13.
  - PL-текст граматично коректний, з діакритикою (ą ć ę ł ń ó ś ź ż). RODO-блок: «Otrzymujesz tę wiadomość, ponieważ poprosiłeś/aś o katalog… zgodnie z Polityką prywatności (RODO)… Aby zrezygnować — kliknij Wypisz się».
- UA-шаблон `mail_template_lead_magnet.xml` лишається без змін.

---

## 5. Views

### 5.1 `views/res_partner_views.xml` (доповнити наявний inherit `view_partner_form_sendpulse`)
Inherited view → **xpath обов'язковий** (правило репо). Кнопка в `<header>`:
```xml
<xpath expr="//sheet" position="before">
  <header>
    <button name="action_send_offer_email" type="object"
            string="Wyślij ofertę" class="btn-primary"
            groups="odoo_chatwoot_connector.group_sendpulse_officer"
            invisible="not email"/>
  </header>
</xpath>
```

### 5.2 `views/crm_lead_views.xml` — НОВИЙ
Inherit `crm.crm_lead_view_form`, xpath на `//header`, кнопка `action_send_offer_email` (`invisible="not email_from"`).

> **Mobile audit** обох views — ОБОВ'ЯЗКОВИЙ перед фіналом коду (правило репо: будь-яка зміна Odoo views).

---

## 6. RODO

- Той самий `sendpulse.privacy.consent.log`, `purpose='lead_magnet_email'`, `channel='email'` (без міграції Selection).
- **F13:** `source='sendpulse_chat'`, `connect_id`, `partner_id`, `message_id`=останнє incoming.
- **Ручний:** `source='admin_manual'` (вже існує), `partner_id`, `legal_basis='consent'`, без `connect_id`/`message_id`.
- Enforcement-gate (`consent_enforcement_enabled`) діє в обох шляхах однаково; перевірка `consent_given=False` ДО send, запис consent — ПІСЛЯ успіху.
- **Узгодження (R2):** ручна кнопка — одинична дія оператора (не масова розсилка); оператор відповідальний за наявність підстави. Якщо є `consent_given=False` → НЕ слати (enforcement спрацьовує).

---

## 7. Manifest / Changelog / реєстрація

- `__manifest__.py`: `version` → `17.0.14.11`; у `data` додати `'data/mail_template_offer_catalog_pl.xml'` та `'views/crm_lead_views.xml'` (після `res_partner_views.xml`). `crm` у depends вже є.
- `models/__init__.py`: `from . import crm_lead`.
- `CHANGELOG.md`: `## [17.0.14.11] — 2026-06-19` — Added: фіча «Wyślij ofertę» (PL offer-каталог через access_token-лінк), channel-independent `res.partner._compose_and_send_offer`, кнопки на `res.partner`+`crm.lead`, F13 → PL+лінк без важкого attachment, RODO-лог `admin_manual` для ручного шляху, новий config-param `offer_pdf_attachment_id`.
- Оновити `CLAUDE.md` (рядок версії) та `docs/CONFIGURATION.md` (нові params + залиття PDF).

---

## 8. Одноразове залиття PDF (НЕ в коді, НЕ в data-XML, документувати)

24 МБ у git заборонено (`.gitignore` + #4ZONES) → НЕ робити data-record і НЕ автоматизувати в коді. Документувати в `docs/CONFIGURATION.md` (секція «PL offer catalog»):
- Варіант UI: Settings → Technical → Attachments → завантажити `CampScout_katalog_2026_PL.pdf` (`public=False`) → скопіювати id у param `offer_pdf_attachment_id`. Токен згенерується автоматично при першому надсиланні.
- Варіант `odoo shell` (за окремим «ок», #4ZONES) — створити `ir.attachment` + `generate_access_token()` + `set_param(...offer_pdf_attachment_id, str(att.id))`.

---

## 9. Deploy-кроки (#4ZONES — НЕ на проді кодом, лише за «ок»)

1. Локально: код + bump + changelog + тести; pre-commit (ruff, OCA — `--fix` НЕ використовувати, зносить self-translations).
2. `git push origin feature/send-offer-link` → PR (commit/push лише за явним «commit/запуши»).
3. На **staging**: `git pull` → залити PL-PDF (UI/shell) → set `offer_pdf_attachment_id` → `lead_magnet_enabled=True` → `docker exec campscout_web odoo -u odoo_chatwoot_connector --stop-after-init && docker restart`.
4. QA staging:
   - (а) кнопка на `res.partner` з email (БЕЗ каналу) → PL-лист приходить, «Pobierz katalog» качає PDF, attachment у листі відсутній, RODO-лог `source=admin_manual` створено;
   - (б) кнопка на `crm.lead`;
   - (в) F13 з каналу → PL-лист+лінк, idempotency тримається (повтор → `already_sent`), RODO `source=sendpulse_chat`;
   - (г) `consent_withdrawn` → skip;
   - (д) regression: F13 UA-flow контракт незмінний; `curl /web/content/{id}?download=true&access_token=...` → 200, ~24 МБ.
5. Mobile-audit рендеру листа + views.
6. Prod — ЛИШЕ після явної команди user і готовності (НЕ за датою): merge у `main` → git pull на проді → `chmod -R o+rX .` → залиття PDF на проді → update → перевірка `latest_version`.

---

## 10. Ризики

- **R1 (головний, знято):** шаблон прив'язаний до `sendpulse.connect`. Рішення — новий PL-шаблон на `res.partner`, рендер через partner-record. Ручний шлях не падає.
- **R2 RODO:** ручний «Wyślij ofertę» = одинична дія оператора, не масова. Enforcement (`consent_given=False` → skip) діє. Без масової розсилки на партнерів без підстави.
- **R3 access_token:** `/web/content?access_token` дає публічний доступ до файлу будь-кому з лінком — прийнятно для каталогу (не PII). Токен НЕ класти в git/CHANGELOG. Не використовувати цей патерн для документів з персональними даними.
- **R4 token стабільність:** `generate_access_token()` лише якщо порожній — інакше старі надіслані лінки протухають.
- **R5 ідемпотентність:** `sp_pdf_sent_at` лишається лише в F13-обгортці (connect-only). Ручний шлях ідемпотентності не має — свідомо (оператор може слати повторно); не баг.
- **R6 дубль хелперів:** при переносі `_get_or_create_public_image`/`_get_email_logo_png_b64` у `res.partner` — grep на використання, копій у connect не лишати.
- **R7 #BOUNDARY:** не чіпати webhook/`mail_channel.py`; лише нові методи + нові data/views + inherit `crm.lead` + перенос 2 хелперів.
- **R8 Gmail clipping / proxy:** лист легший без 24 МБ — покращення; перевірити що PL-HTML < ~102 КБ; nginx download великого файлу (timeout) — перевірити на staging.
- **R9 Польська граматика:** діакритика + вичитка перед merge (правило репо).

---

## 11. Файли, що змінюємо/створюємо (абсолютні шляхи)

- M `/Users/admin/Developer/Fayna-Projects/fayna-sendpulse-odoo/models/sendpulse_connect.py` — F13 → делегування; виніс 2 хелперів
- M `/Users/admin/Developer/Fayna-Projects/fayna-sendpulse-odoo/models/res_partner.py` — `_compose_and_send_offer`, `action_send_offer_email`, перенесені `_get_or_create_public_image`/`_get_email_logo_png_b64`
- A `/Users/admin/Developer/Fayna-Projects/fayna-sendpulse-odoo/models/crm_lead.py` + M `models/__init__.py`
- A `/Users/admin/Developer/Fayna-Projects/fayna-sendpulse-odoo/data/mail_template_offer_catalog_pl.xml`
- M `/Users/admin/Developer/Fayna-Projects/fayna-sendpulse-odoo/views/res_partner_views.xml` + A `/Users/admin/Developer/Fayna-Projects/fayna-sendpulse-odoo/views/crm_lead_views.xml`
- M `/Users/admin/Developer/Fayna-Projects/fayna-sendpulse-odoo/__manifest__.py`, `CHANGELOG.md`, `CLAUDE.md`, `docs/CONFIGURATION.md`
- (опц.) M `/Users/admin/Developer/Fayna-Projects/fayna-sendpulse-odoo/models/res_config_settings.py` + `views/res_config_settings_views.xml` (поле attachment_id)
- (опц.) A `/Users/admin/Developer/Fayna-Projects/fayna-sendpulse-odoo/tests/test_offer_email.py` (рендер лінку, RODO-skip, no_email, disabled-noop, manual без connect)
