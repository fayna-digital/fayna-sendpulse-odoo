# TZ — i18n даних та клієнтських повідомлень за стандартами Odoo

> Статус: **ЧЕРНЕТКА — чекає затвердження** · Автор: Claude + Volodymyr · Дата: 2026-06-12
> Контекст: UI-переклад модуля (PL/UA, 654 терміни, v17.0.14.8) виконано. Це ТЗ — про **дані**
> і **вихідні повідомлення клієнтам**, де зараз костилі замість штатних механізмів Odoo.

## 1. Objective

Привести багатомовність модуля до канону Odoo 17, прибравши тимчасові рішення:

| # | Зараз (костиль) | Має бути (Odoo-канон) |
|---|---|---|
| K1 | Клієнтські тексти у 8 `ir.config_parameter` — один рядок на всіх, UA-дефолти зашиті в py | Перекладні записи: текст рендериться **мовою клієнта** з fallback-ланцюгом |
| K2 | `sendpulse.public.template.text` без `translate` (а `name` — явний `translate=False`) | `translate=True` + вибір версії за мовою аудиторії |
| K3 | `language_code` — вільний `Char` із SendPulse (`uk`/`en`/`ru`…), ні до чого не прив'язаний | Мапінг на `res.lang` (`uk→uk_UA`, `pl→pl_PL`…), синхронізація в `res.partner.lang` |
| K4 | Привітання/drip/goodbye шлються без огляду на мову клієнта | Усі вихідні тексти проходять рендер у `client_lang` |
| K5 | `faq.entry` `translate=True` додано точково (12.06), RAG запінено на `en_US` | Лишити; додати тест-інваріант + політику заповнення PL-версій |
| K6 | Source-мова msgid = українська (маскується під `en_US`) | **Прийняте відхилення** — зафіксувати документально (повна міграція на EN-source = окремий проєкт, зараз не виправдана) |

**Інваріант (не ламати):** AI-бот сам відповідає мовою клієнта (LLM + `_translate_text`) —
це ТЗ стосується **детермінованих** текстів (привітання, drip, шаблони), не AI-генерації.

## 2. Commands

```bash
# Розробка — як у docs/TZ.md (lint/тести/деплой ті самі)
ruff check . && ruff format --check .
python -m pytest tests/ -v          # нові тести цього ТЗ — обов'язкові

# Перегенерація i18n-шаблону після змін полів/рядків (КАНОН — лише так):
docker exec campscout_web odoo -c /etc/odoo/odoo.conf -d <db> \
  --i18n-export=/tmp/odoo_chatwoot_connector.pot --modules=odoo_chatwoot_connector \
  --stop-after-init --no-http
```

## 3. Project Structure (зміни)

```
models/
  sendpulse_client_message.py   # НОВА модель: ключ + текст(translate=True) + active
  sendpulse_connect.py          # client_lang (compute) + _get_client_text(); виклики замість get_param
  sendpulse_public_template.py  # translate=True на name+text
  res_config_settings.py        # текстові параметри → посилання на client.message (поля прибрати)
data/
  sendpulse_client_message_data.xml  # noupdate=1: 8 ключів з поточними дефолтами як base
migrations/17.0.15.0/
  post-migrate.py               # params → записи client.message (значення з прод-БД, не з коду)
tests/
  test_client_lang_mapping.py   # K3: language_code→res.lang, невідомі коди
  test_client_message_render.py # K1: fallback-ланцюг client_lang→uk_UA→base
  test_rag_lang_invariant.py    # K5: get_active_faq_for_prompt завжди en_US-source
i18n/                            # регенерувати .pot; доперекласти нові терміни pl/uk
```

### 3.1 Нова модель `sendpulse.client.message`

```python
_name = 'sendpulse.client.message'
key = fields.Char(required=True, index=True)        # 'new_contact_greeting', 'drip_reminder_6h', ...
text = fields.Text(required=True, translate=True)   # ← мовні версії через стандартний перемикач
active = fields.Boolean(default=True)
_sql_constraints = [('key_uniq', 'unique(key)', ...)]
```

8 ключів (повна інвентаризація 12.06): `new_contact_greeting`, `new_contact_greeting2`,
`sp_comment_private_text`, `auto_close_goodbye_text`, `drip_reminder_6h_text`,
`drip_booking_3d_text`, `lead_magnet_email_subject`, `lead_magnet_sms_template`.
(`mail_template_lead_magnet_catalog` — вже `mail.template`, має рідний lang-рендер: лише
переконатись, що викликається з lang партнера.)

### 3.2 Мапінг мови (K3)

```python
_SP_LANG_MAP = {'uk': 'uk_UA', 'pl': 'pl_PL', 'en': 'en_US', 'ru': '<RU-POLICY>'}
client_lang = fields.Selection(..., compute='_compute_client_lang', store=True)
# compute: _SP_LANG_MAP.get(language_code) ∩ активні мови БД; fallback → 'uk_UA'
```
При identify (прив'язка partner) — синхронізувати у `res.partner.lang`, **не перетираючи**
вручну виставлене значення (тільки якщо partner.lang порожній/дефолтний).

### 3.3 Рендер (K1, K4)

```python
def _get_client_text(self, key):
    msg = self.env['sendpulse.client.message'].with_context(lang=self.client_lang)...
    # fallback: client_lang → uk_UA → base(en_US); '' якщо запис inactive
```
Усі 6 точок відправки (greeting ×2, comment private, goodbye, drip ×2) + lead magnet —
через `_get_client_text`. Плейсхолдери (`{landing_url}`, `{tg_url}`, імʼя) — підстановка
ПІСЛЯ вибору мовної версії; тест на збереження плейсхолдерів у кожній версії.

## 4. Code Style

- Як docs/TZ.md (ruff, line-length 100, single quotes).
- `.po` — ТІЛЬКИ від `--i18n-export` шаблону (occurrence-коментарі обов'язкові; інцидент
  12.06: msgid без них Odoo «вантажить», але не застосовує).
- `po-pretty-format` вимкнено `.oca_hooks.cfg` — НЕ вмикати (зрізає 506 uk self-translations).
- Migration читає старі params з БД і переносить у записи; params потім видалити
  (один реліз тримати read-fallback `param or record` — потім зачистити).

## 5. Testing Strategy

| Тест | Перевіряє |
|---|---|
| `test_client_lang_mapping` | `uk→uk_UA`, `pl→pl_PL`, невідомий код → fallback; порожній → fallback |
| `test_client_message_render` | pl-клієнт ← pl-текст; без pl-версії ← base; inactive ← '' |
| `test_placeholders_survive` | `{landing_url}`/`{tg_url}` цілі в кожній мовній версії |
| `test_rag_lang_invariant` | RAG-вибірка ідентична незалежно від `env.lang` оператора |
| `test_migration_params` | після migrate: записи = старі значення params, base-мова |
| Preflight на копії прод-БД | повна репетиція `-u` (процедура з 12.06: `_preflight` + `campscout_preflight`) перед прод-деплоєм — ОБОВ'ЯЗКОВА |

## 6. Boundaries

- **НЕ чіпати:** AI-промпти/`_translate_text`, webhook-логіку, `omnichannel_bridge`,
  `zadarma_odoo`, тексти що бот генерує LLM-ом (вони і так мовою клієнта).
- **НЕ робити** в цьому ТЗ: міграцію source-мови на EN (K6 — прийняте відхилення,
  окреме рішення якщо колись піде продаж модуля назовні); переклад `campscout_management`
  (DEPRECATED) — окреме питання.
- RODO-тексти згод — юридичні формулювання: зміна мовних версій ТІЛЬКИ з затвердженими
  перекладами (не машинними).

## Фази та оцінка

| Фаза | Зміст | Оцінка | Ризик |
|---|---|---|---|
| P0 | Закрити Open Questions (нижче) | 0.5 год розмови | — |
| P1 | K3: мапінг + `client_lang` + sync у partner | 2-3 год | низький |
| P2 | K1: модель + data + migration params→records | 3-4 год | середній (migration) |
| P3 | K2: translate на public.template | 1 год | низький |
| P4 | K4: 6 точок відправки через `_get_client_text` | 2-3 год | середній (поведінка клієнтам!) |
| P5 | Тести + .pot regen + допереклад + preflight + деплой | 3-4 год | низький |

Разом ~12-15 год. Кожна фаза = окремий PR; P4 деплоїться з прапорцем
`client_message_lang_enabled` (default off → smoke на проді → on).

## Success Criteria

1. Польськомовний клієнт (language_code=pl) отримує greeting/drip/goodbye польською;
   україномовний — українською; без перекладу — base-текст (як сьогодні), не порожньо.
2. Оператор бачить на записах client.message/public.template/faq стандартний перемикач
   мов Odoo і редагує версії без розробника.
3. Жодного клієнтського тексту в `ir.config_parameter` і жодного UA-дефолту в py-коді.
4. RAG-інваріант зелений; поведінка AI-відповідей не змінилась.
5. Всі тести зелені в CI; preflight-репетиція `-u` чиста; CHANGELOG + версія 17.0.15.0.

## Open Questions (до P0)

1. **RU-політика:** клієнтам з `language_code=ru` слати uk_UA чи окремі ru-тексти?
   (активувати ru_RU у БД — окреме рішення з наслідками для всього UI).
2. **lead_magnet_sms_template** — SMS коштує грошей: чи потрібні мовні версії, чи лишити одну?
3. Хто і коли заповнює PL-версії 8 client-messages та 10 FAQ (Daniel? Iryna?) —
   деплой P4 має сенс лише після заповнення.
4. `sp_comment_private_text` шле і **public reply** під коментар — мову брати з
   language_code автора коментаря (його часто нема у FB API) чи з мови сторінки?

## Зв'язки

[[TZ.md]] · [[REPO_STANDARD]] · memory: `project_i18n_zadarma_omni_2026-06-12`
(уроки .po/occurrence/preflight) · інцидент po-pretty-format 2026-05-06
