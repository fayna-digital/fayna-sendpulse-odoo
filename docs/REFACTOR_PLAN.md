# `sendpulse_connect.py` — План розбиття (Фаза 2, «345»)

> Стан на коміт `b23edba` (20.07.2026), файл 5649 рядків, `class SendpulseConnect(models.Model): _name = 'sendpulse.connect'`.
> Цей документ — лише план. Код ще не чіпали (Фаза 3 виконує його крок за кроком).
> Контекст і повний Odoo/OCA аудит (10 пунктів) — `~/Developer/Fayna-Workspace/Projects/DevJournal/claude-memory/project_sendpulse_refactor_brief_345_2026-07-20.md`.

## 0. Ключове архітектурне рішення

Модель `sendpulse.connect` має дуже широку зовнішню поверхню, прив'язану до **точного імені моделі**, не до файлу:

- View-кнопки (`views/sendpulse_connect_views.xml`): `action_open_discuss`, `action_identify_partner`, `action_close`, `action_reopen`, `action_fetch_contact_info`, `action_sync_discuss_channels`.
- JS RPC з хардкодженим ім'ям моделі (`static/src/components/sendpulse_info_panel/sendpulse_info_panel.js`, 8 викликів `orm.call("sendpulse.connect", "...")`): `get_connect_for_channel`, `unarchive_partner_for_channel`, `suggested_reply_for_channel`, `translate_last_inbound_for_channel`, `send_pdf_catalog_for_channel`, `send_sms_coupon_for_channel`.
- `ir.cron` (`data/clean_data_cron.xml`, 10 записів з `model_id ref="model_sendpulse_connect"`).
- `ir.model.access.csv` і `security.xml` (record rules `rule_sendpulse_connect_officer/admin`).
- `mail_channel.py` (`_inherit = 'discuss.channel'`) читає `self.sendpulse_connect_id`, викликає `connect.send_message_to_sendpulse()`, `connect._get_service_label()`, `connect._get_channel_description()`.
- `controllers/main.py` викликає `request.env['sendpulse.connect'].sudo()._process_incoming_event(...)` / `_process_outgoing_event(...)` / `_process_unsubscribe(...)`.
- `sendpulse_identify_wizard.py` викликає `connect.assign_partner(partner.id)`.

**Рішення:** `_inherit`-шардинг ОДНОГО `_name='sendpulse.connect'` на кілька Python-файлів, без нового `_name` у файлах-розширеннях — точно так само, як вже зроблено `mail_channel.py` (`_inherit = 'discuss.channel'`) і `res_partner.py` (`_inherit = 'res.partner'`) у цьому репо. Це офіційний Odoo/OCA-патерн для великих моделей.

Odoo збирає всі `_inherit`-класи в один клас реєстру ПЕРЕД тим, як щось викликається — `self._method()` резолвиться однаково незалежно від фізичного файлу. **Порядок імпорту файлів у `models/__init__.py` не впливає на коректність виклику методів.**

```python
class SendpulseConnectWebhook(models.Model):
    _inherit = 'sendpulse.connect'
    # тільки методи, жодних нових fields (якщо не потрібно) і жодного _name
```

Поля (`fields.Char/...`) залишаються ЛИШЕ в головному файлі `sendpulse_connect.py` (core: field definitions + `init()` + `_compute_*` + `create/write/unlink`) — переносити оголошення полів окремо технічно можливо, але без вигоди й з ризиком розʼїзду `@api.depends`.

**Не робити зараз:** перенесення Meta API-методів на окрему модель `sendpulse.facebook.page` (вищий ризик, зміна сигнатур) — окрема майбутня фаза за потреби, не Фаза 3.

## а) Таблиця: кластер → методи → цільовий файл

| # | Кластер | Методи / атрибути (рядки, b23edba) | Цільовий файл |
|---|---|---|---|
| 0 | Core / поля / ORM / Discuss-лайфсайкл | усі `fields.*`, `init()`, `_compute_*` (5), `create/write/unlink`, `action_open_discuss`, `action_identify_partner`, `action_close`, `action_reopen`, `_create_discuss_channel`, `_send_autoreply_greeting`, `_get_service_label`, `_get_channel_description`, `_close_channel`, `action_sync_discuss_channels`, `cron_sync_discuss_channels`, `_post_history_to_partner`, `assign_partner`, `_update_partner_source`, `_notify_operators_new_conversation`, `_notify_operators_new_message`, `_find_partner`, `_record_conversation_message`, `get_connect_for_channel`, `unarchive_partner_for_channel`, `cron_auto_close_inactive` | `sendpulse_connect.py` (→ ~1300 рядків) |
| 1 | OAuth (SendPulse API токен) | `_sendpulse_oauth_invalidate_cache`, `_sendpulse_oauth_read_cache_db`, `_sendpulse_oauth_do_refresh`, `_get_access_token` (896–1007) | `sendpulse_oauth.py` |
| 2 | Telegram notify | `_notify_telegram` (2050–2087) | `sendpulse_telegram_notify.py` |
| 3 | Webhook processing (ядро) | `_process_incoming_event`, `_process_outgoing_event`, `_process_unsubscribe`, `_download_media_as_attachment`, `_is_allowed_media_url`, `_ALLOWED_MEDIA_DOMAINS`, `_MEDIA_MAX_BYTES` (1093–1499, 4637–4835) | `sendpulse_webhook.py` |
| 4 | FB/IG коментарі — автовідповідь+LLM-класифікація | `_process_comment_event`, `_classify_comment`, `_notify_operator_comment`, `_COMMENT_PUBLIC_TEMPLATES`, `_COMMENT_PUBLIC_REPEAT_TEMPLATE`, `_COMMENT_CATEGORIES`, `_CATEGORY_LABELS`, `cron_archive_old_comment_records` (1520–1850, 2368–2401, 4521–4582) | `sendpulse_comment_autoreply.py` |
| 5 | Meta/FB Graph API — токени, sends, retry | `_log_fb_audit`, `_fb_post_with_retry`, `_maybe_alert_token_expired`, `_exchange_token_for_long_lived`, `cron_refresh_fb_tokens`, `_hide_comment`, `_send_comment_public_reply`, `_send_comment_private_reply`, `_get_fb_page_token`, `cron_check_messenger_windows`, `_check_single_fb_token`, `cron_check_fb_token_expiry`, `_parse_fb_error` (1911–2048, 4079–4520) | `sendpulse_meta_api.py` |
| 6 | CRM lead auto-create | `_auto_create_crm_lead` (2185–2314) | `sendpulse_crm_lead.py` |
| 8 | Weekly Telegram-звіт + live dialogs-моніторинг | `cron_weekly_telegram_report`, `_calculate_weekly_stats`, `_format_weekly_report`, `cron_check_dialogs_snapshot`, `_DIALOGS_URL` (2091–2183, 2402–2594) | `sendpulse_reporting.py` |
| 9 | RODO consent (unsubscribe) — БАГ ТУТ | `_check_and_record_unsubscribe`, `UNSUBSCRIBE_PATTERNS` (2596–2688) | `sendpulse_rodo.py` |
| 10 | AI: suggested replies + RAG FAQ + переклад + email-extract | `_get_live_events_context`, `_generate_reply_suggestions`, `suggested_reply_for_channel`, `_try_extract_email_and_link`, `_translate_text`, `translate_last_inbound_for_channel`, `_rag_answer_question`, `_try_rag_auto_answer`, `_EMAIL_REGEX` (F12, 2992) (2690–3146, 3507–3796) | `sendpulse_ai_assist.py` |
| 11 | Lead magnet PDF/SMS | `_send_pdf_catalog_email`, `_get_email_logo_png_b64`, `_get_or_create_public_image`, `_generate_and_send_sms_coupon`, `send_pdf_catalog_for_channel`, `send_sms_coupon_for_channel` (3149–3505) | `sendpulse_lead_magnet.py` |
| 12 | Drip campaigns | `_check_drip_stop_keyword`, `_can_send_drip_message`, `cron_drip_followups`, `_DRIP_STOP_KEYWORDS` (3786–3939) | `sendpulse_drip.py` |
| 13 | Bot-wizard ідентифікації | `_is_identification_eligible_service`, `_try_start_identification`, `_try_advance_identification`, `_EMAIL_REGEX` (F3, 3942), `_ID_ASK_EMAIL_FIRST`/`_ID_ASK_EMAIL_RETRY`/`_ID_THANKS`/`_ID_GAVE_UP` (3941–4076) | `sendpulse_identification.py` |
| 14 | Профіль/avatar sync | `action_fetch_contact_info`, `_sync_avatar_to_partner`, `_extract_contact_vals`, `_CONTACT_GET_ENDPOINTS`, `_SP_STATUS_MAP`, `_SP_STATUS_INT_MAP` (4859–5031) | `sendpulse_profile_sync.py` |
| 15 | Вихідні повідомлення — core sending + auto-split + pull-missing cron | `_split_text_by_limit`, `send_message_to_sendpulse`, `_send_single_message`, `_SERVICE_TEXT_LIMITS`, `cron_pull_missing_contacts`, `_CONTACT_LIST_ENDPOINTS` (5147–5649) | `sendpulse_messaging.py` |

Разом: 15 файлів (Core + 14 нових `_inherit`-шардів).

## б) Підхід по файлах

- Усі 14 нових файлів → `_inherit = 'sendpulse.connect'`, БЕЗ `_name` — єдиний варіант, що не ламає жодне зовнішнє посилання.
- Не окремі `models.Model` з новим `_name` — усі кластери тримають стан через ті самі поля (одна таблиця).
- Не mixin/`AbstractModel` — поведінка не перевикористовується кількома різними моделями, лише однією.
- OAuth (#1) і Telegram-notify (#2) — кандидати на майбутнє перетворення у прості service-класи (не ORM), не читають/не пишуть `self`-поля. У Фазі 3 — лишаються `_inherit`-шардом; перетворення в окремий сервіс-клас — опційна майбутня ітерація, не зараз.
- Meta API (#5) — стретч-ціль перенести на `sendpulse.facebook.page` пізніше, зараз `_inherit`-шард.
- Кожен новий файл — лише методи + пов'язані class-level константи цього кластера, докстрінг зверху пояснює межі кластера.

## в) Залежності між кластерами (для оцінки ризику й порядку, не для import-порядку)

```
Webhook (#3)  ──calls──▶ Core (#0): _find_partner, _create_discuss_channel,
                          _send_autoreply_greeting, _record_conversation_message,
                          _update_partner_source
              ──calls──▶ Identification (#13), RODO (#9), CRM Lead (#6),
                          AI-assist (#10) _try_rag_auto_answer,
                          Comment-autoreply (#4), Meta API (#5) (тільки з
                          комент-гілки), Telegram (#2)

Comment-autoreply (#4) ──calls──▶ Meta API (#5), Telegram (#2)

Meta API (#5) ──calls──▶ Telegram (#2); self-calls _fb_post_with_retry

Messaging (#15) ──called by (НАЙВИЩИЙ fan-in)──: Core greeting, Drip (#12),
                  Identification (#13), AI-assist (#10), cron_auto_close_inactive,
                  mail_channel.py (ззовні)

OAuth (#1) ──called by (fan-in)──: Messaging (#15), Webhook (#3),
             Profile-sync (#14), cron_pull_missing_contacts

Reporting (#8) ──calls──▶ Telegram (#2), OAuth (#1); reads Meta API (#5) і
                Comment-autoreply (#4) дані

Lead-magnet (#11) ──calls──▶ RODO-суміжне (sendpulse.privacy.consent.log),
                   res_partner.py (вже окремий файл, не God Object)

AI-assist (#10) ──calls──▶ Messaging (#15), Core (#0) _find_partner
Drip (#12) ──calls──▶ Messaging (#15), Telegram (#2)
Identification (#13) ──calls──▶ Messaging (#15)
Profile-sync (#14) ──calls──▶ OAuth (#1)
```

**Найважливіші знахідки:**

1. `_record_conversation_message` (Core) — навмисний спільний helper, лишається в Core, доступний Webhook і Core однаково через `_inherit`-merge.
2. `send_message_to_sendpulse` (Messaging #15) — найвищий fan-in (≈8 кластерів + `mail_channel.py`). Blast radius найширший, компенсація: метод самодостатній (не читає чужих полів).
3. **Прихована колізія:** клас двічі визначає `_EMAIL_REGEX` (рядок 2992 F12, рядок 3942 F3) — друге визначення Python-перекриває перше на рівні класу, тобто `_try_extract_email_and_link` (F12) фактично користується F3-регексом, не власним. Після розбиття на файли #10/#13 колізія природно зникає (кожен матиме свій клас-атрибут) — **явно перейменувати** (`_EMAIL_REGEX_F12`/`_EMAIL_REGEX_F3`) або звести до одного спільного в Core, рішення на кроці 9.
4. Meta API (#5) — фізично розтягнутий по файлу (рядки 1911–2048 і 4079–4520, між ними webhook/comment/RODO/AI/lead-magnet/drip/identification). Об'єднання в один файл — найбільша практична вигода рефакторингу.

## г) Послідовність міграції (від найменш ризикованого)

| Крок | Кластер → файл | Чому цей порядок | Тестове покриття |
|---|---|---|---|
| 1 | OAuth → `sendpulse_oauth.py` | Найменший (4 методи, ~110 рядків), нуль ORM-полів, нуль XML/JS-поверхні. «Суха репетиція». | Непряме |
| 2 | Telegram notify → `sendpulse_telegram_notify.py` | 1 метод, нуль полів/XML/JS/cron. Другий тренувальний крок. | Немає |
| 3 | RODO → `sendpulse_rodo.py` (+ фікс бага) | Найкраще покритий кластер (9 тестів `test_rodo_consent.py`, 2 з них навмисно документують поточний баг). Перенесення + фікс `self.sp_contact_id`→`self.sendpulse_contact_id` (рядок 2670) одним кроком. | ✅ 9 тестів |
| 4 | CRM Lead → `sendpulse_crm_lead.py` | Малий, чисті межі. | ✅ `test_auto_create_lead.py` (7) |
| 5 | Drip → `sendpulse_drip.py` | Середній, чисті межі, залежить лише від Messaging (self-виклик, ОК). | Немає |
| 6 | Identification → `sendpulse_identification.py` | Викликається з Webhook — робити після підтвердження паттерну (кроки 1–5). | Непряме |
| 7 | Профіль/avatar sync → `sendpulse_profile_sync.py` | Кнопка `action_fetch_contact_info` — «тренування» на button-переносі перед великим #0. | Немає |
| 8 | Lead magnet → `sendpulse_lead_magnet.py` | 2 RPC-методи хардкоджені в JS — перший крок, що торкається JS RPC contract, перевірити OWL-панель вручну. | Немає |
| 9 | AI-assist → `sendpulse_ai_assist.py` | Найбільший «простий» файл (~650 рядків), 2 RPC-методи, вирішити `_EMAIL_REGEX`-колізію тут. | Немає |
| 10 | Meta API → `sendpulse_meta_api.py` | 3 крони перевірити в `ir.cron` після переносу; споживається Webhook і Comment-autoreply. | Немає |
| 11 | Comment-autoreply → `sendpulse_comment_autoreply.py` | Залежить від щойно перенесеного Meta API — одразу після. | Непряме |
| 12 | Reporting → `sendpulse_reporting.py` | Читає дані майже з усіх кластерів — робити коли всі read-джерела стабільні. 3 крони. | Немає |
| 13 | **Webhook → `sendpulse_webhook.py`** | Найризикованіший — ядро продукту, найвищий fan-out. Найбільше тестів (`test_process_incoming_event.py`, `test_process_outgoing_event.py`, `test_find_partner.py`, `test_record_conversation_message.py`, 25+). Передостанній, коли всі залежності вже стабільні. | ✅✅ 25+ тестів |
| 14 | **Messaging → `sendpulse_messaging.py`** | Найвищий fan-in — робити останнім, коли всі споживачі перенесені й протестовані. Один цілісний regression-прогін після. | Непряме |

**DoD кожного кроку:** git diff = переміщення методів + оновлення `models/__init__.py` + жодних інших правок логіки (крім кроку 3 — задокументований баг-фікс). Після кожного кроку — прогнати Фаза-1 тести (42) і, де можливо, весь модуль (`-i odoo_chatwoot_connector --test-enable`).

## д) Що перевірити після КОЖНОГО кроку

1. `models/__init__.py` — новий файл доданий в `from . import (...)`, інакше Odoo мовчки не завантажить `_inherit`-клас.
2. `-u odoo_chatwoot_connector --stop-after-init` на staging без помилок реєстрації моделі.
3. `ir.cron` (`data/clean_data_cron.xml`) — усі 10 записів резолвляться (перевірка через `odoo shell` або ручний запуск `env['sendpulse.connect'].cron_xxx()`).
4. View-кнопки (`views/sendpulse_connect_views.xml`) — відкрити форму, натиснути кожну кнопку. Критично для кроків 0 (Core) і 7 (Profile sync).
5. JS RPC (`sendpulse_info_panel.js`) — відкрити SendPulse-розмову в Discuss, перевірити OWL sidebar-панель. Критично для кроків 8 і 9.
6. `security/ir.model.access.csv`, `security/security.xml` — не потребують правок при `_inherit`-шардингу, підтвердити один раз на кроці 1.
7. `controllers/main.py` / `controllers/meta_lead_webhook.py` — прогнати реальний webhook-запит на staging. Критично на кроці 13.
8. `mail_channel.py` — відповідь оператора в Discuss дійсно йде в SendPulse. Критично на кроці 14.
9. Odoo test-runner — увесь `tests/` (42+ тестів) зелений після КОЖНОГО кроку, не лише в кінці.
10. Крок 3 окремо: обидва тести (`test_unidentified_contact_crashes_on_messenger_branch`, `test_unidentified_contact_with_booking_email_partial_write_before_crash`) МАЮТЬ впасти після фіксу (задокументовано в docstring) — переписати під новий контракт.
11. `__manifest__.py` — бампнути версію (зараз `17.0.15.8`) після фінального кроку 14.

## Підсумок

- 15 файлів замість 1: `sendpulse_connect.py` (core, ~1300 рядків) + 14 нових (~250–650 рядків кожен).
- 1 задокументований баг виправляється у кроці 3 (RODO).
- 1 прихована колізія констант (`_EMAIL_REGEX`) вирішується у кроці 9.
- Нуль змін зовнішньої поведінки очікується у кроках 1–2, 4–14 (чисте механічне перенесення); крок 3 — єдиний з навмисною зміною поведінки, узгодженою наперед двома тестами.
