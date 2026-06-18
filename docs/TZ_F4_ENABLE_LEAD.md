# ТЗ — Увімкнення F4 chat→лід + закриття дір (lead-трек)

> #BOUNDARY: модуль чіпаємо лише за цим ТЗ. 3 інциденти AI-самоправок —
> код ТІЛЬКИ після «ок» user. Шлях: repo → GitHub → staging → prod.

## 1. Objective

SendPulse-розмова, де клієнт **реально відповів** у приваті, має автоматично
ставати `crm.lead` — щоб ліди з чатів (Telegram/IG/FB/WA/Viber) не губились
(зараз лише `discuss.channel`, лід заводять руками → діра, через яку «загубилась»
Aldona).

## 2. Поточний стан (перевірено, read-only)

- Метод `SendpulseConnect._auto_create_crm_lead()` (`models/sendpulse_connect.py`)
  **готовий і якісний**: ідемпотентний (`sp_lead_id`), вимагає контакт
  (partner / email / phone / social_username), ставить source/team/user, опис з
  останніх 5 повідомлень, лінкує партнера, нотатка в Discuss, `try/except`.
- Тригер: викликається коли `sp_funnel_stage` → `customer_replied` (клієнт
  вперше відповів). Ідемпотентно.
- **Вимкнено конфігом:** `odoo_chatwoot_connector.auto_create_lead_enabled` != True.
- **Налаштування є** в `res.config.settings`: `auto_create_lead_enabled`,
  `auto_create_lead_team_id`.

Висновок: це **увімкнення + тести**, не нова логіка.

## 3. Зміни (scope)

1. **`data/ir_config_parameter.xml`** (або окремий файл) — увімкнути:
   - `odoo_chatwoot_connector.auto_create_lead_enabled = True`
   - `odoo_chatwoot_connector.auto_create_lead_team_id = <team_id>` (див. Open).
   *(noupdate-режим уточнити: щоб ручне вимкнення в UI не перетиралось при -u.)*
2. **`tests/test_auto_create_lead.py`** (ДІРА #1 — 0 тестів у модулі):
   - `customer_replied` + є контакт → створюється 1 `crm.lead`, `sp_lead_id` set.
   - ідемпотентність: повторний виклик не дублює.
   - немає контакту (ні partner/email/phone/username) → лід НЕ створюється.
   - `auto_create_lead_enabled=False` → no-op.
   - лінк партнера: `partner_id`/`email_from`/`phone` проставлені.
   - title `[service] name`, team/source проставлені.
3. **Ліцензія** (ДІРА #2): `LGPL-3` → `OPL-1` (house-style, як інші CampScout-модулі).
4. **Назва** (ДІРА #3): тех-назву `odoo_chatwoot_connector` НЕ чіпати (ризик
   посилань у даних) — задокументувати в README/CLAUDE як legacy від форку Chatwoot.

## 4. Boundaries / ризики

- Тех-назву модуля не перейменовуємо.
- Увімкнення = більше лідів (кожна зацікавлена розмова). `customer_replied`
  (а не кожне повідомлення) тримає шум низьким; контакт обовʼязковий.
- SendPulse-ліди мають назву `[service] name` (не `Zgłoszenie`/`Заявка`) і не
  мають вхідного `mail.message(email)` → модуль `fayna_camp_lead_sms` на них SMS
  НЕ шле (узгоджено: SendPulse видно в SendPulse). Конфлікту нема.
- Деплой: staging `--test-enable` (тести зелені) → прод `-u` + restart.

## 5. Success Criteria — ✅ ВИКОНАНО 2026-06-18 (v17.0.14.10)

- [x] `auto_create_lead_enabled=True` на проді (через `data/lead_autocreate_config.xml`,
      noupdate, team=Sales) — перевірено.
- [x] Тести lead-шляху зелені на staging: **0 failed, 0 error(s) of 6 tests**
      (`tests/test_auto_create_lead.py` — було 0 тестів у модулі).
- [x] Контроль на проді: розмова з контактом → 1 лід у лійці Sales **без
      відповідального** (пул), `sp_lead_id` set, повтор → той самий лід; без
      контакту → 0.
- [x] `_auto_create_crm_lead`: `user_id=False` (пул, замість лідера команди).
- [x] Ліцензія `OPL-1`; legacy-назва `odoo_chatwoot_connector` задокументована
      (README/CLAUDE/TECHNICAL_DOCS/INDEX). Apps-опис (static/description) оновлено.
- [x] health-check SendPulse після деплою: webhooks 200, токени valid, крони
      активні, 0 ERROR модуля.

**Деплой:** repo → GitHub (fayna-sendpulse-odoo) → staging (тести green) → prod.
**Беклог (не сьогодні):** WARNING `handle_webhook ignoring args {token}` (косметика);
Фаза 2 — ширше тест-покриття (webhook/identify/routing).

## 6. Рішення (узгоджено 2026-06-18)

- **Team:** `crm.team` **id=1 «Sales/Продажі»** — основна лійка (806 лідів/90д),
  туди ж падають лендінг/пошта. SendPulse-ліди — в неї.
- **Модель призначення: A — пул + claim.** Лід падає **без відповідального**
  (`user_id = False`), менеджер «бере собі» з лійки → інші бачать, що зайнято.
  Це вимагає правки `_auto_create_crm_lead`: зараз ставить `user_id =
  team.user_id` (лідер) → **прибрати** (лишити пустим). НЕ round-robin.
- `noupdate`: config-параметр увімкнення з `noupdate="1"` — щоб ручне
  вимкнення в UI не перетиралось при `-u`.
