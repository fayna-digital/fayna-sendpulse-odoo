# Інцидент — можлива втрата вхідних повідомлень SendPulse↔Odoo (2026-07-19)

<div style="color:#8a6d00; border:2px solid #8a6d00; padding:14px 18px; margin:0 0 20px; background:#fffbea;">

**Статус: РОЗСЛІДУВАНО + ЧАСТКОВО ВИПРАВЛЕНО (staging), прод чекає деплою**
**Тип:** race condition у webhook-обробці → тиха втрата даних (не AI-інцидент — реальний продуктовий баг)
**Тригер:** усний репорт менеджера («у деяких клієнтів позникала частина переписки»)

</div>

Це — технічний журнал розслідування: що перевірялось, що виявилось хибною тривогою, що виявилось реальним багом, які фікси застосовано і що лишається відкритим. Написано ПІСЛЯ факту, з реальних команд і результатів (не з памʼяті).

---

## 1. Тригер

19.07.2026 менеджер (Юрій Яковенко) повідомив: «у деяких клієнтів у Оду позникала частина переписки». Скріншот показував Odoo Discuss канал одного конкретного клієнта поруч зі SendPulse-логом тієї ж розмови.

## 2. Перевірка конкретного прикладу — хибна тривога

Канал `[TG]Alevtyna Myrgorodska` (`discuss.channel` id 5852). Пряма звірка `mail_message` у prod БД проти SendPulse-логу: повідомлення «Добрий день» 02.07.2026 присутнє (id 384241, `date=2026-07-02 16:00:55 UTC` = 19:00:55 Київ — точний збіг з UTC+3). Уся історія каналу 23.06–19.07 неперервна.

**Висновок:** нічого не зникло. Те, що виглядало як втрата — просто scroll-позиція Discuss (відкрився на «Сьогодні», старіші записи не влізли у в'юпорт).

## 3. Глибша перевірка — знайдено реальний баг

За проханням «перевір ще раз»: `pg_stat_user_tables` на `mail_message` показав 16 481 реальний DELETE проти 92 078 INSERT з моменту рестарту Postgres (24.06→19.07, 25 днів). Ретеншен-крон `omni_cron_purge_old_messages` (`omnichannel_bridge`, 180 днів) виключено — не міг чіпати місячну переписку.

**Корінь**, `odoo_chatwoot_connector/controllers/main.py` + `models/sendpulse_connect.py::_update_partner_source` (стан ДО фіксу):

1. Уся обробка вхідного вебхука (включно з raw-audit записом `sendpulse.webhook.data`) йшла в ОДНІЙ Odoo-транзакції (Odoo = одна транзакція на HTTP-request).
2. `_update_partner_source()` робив raw SQL `UPDATE partner_sendpulse_channel SET message_count = message_count + 1` **без savepoint**.
3. Два майже одночасні webhook-и по тому самому клієнту (клієнт пише кілька повідомлень поспіль) ловили Postgres `could not serialize access due to concurrent update`.
4. Виняток абортував **всю** транзакцію запиту — включно з уже створеним `sendpulse.message` і навіть raw-audit записом. Нічого не лишалось.
5. Контролер ловив виняток, але `_json()` жорстко ставив **HTTP status=200** навіть на помилку → SendPulse бачив «200 OK», вважав доставку успішною, **ніколи не ретраїв**. Повідомлення клієнта зникало безслідно, без сліду для відновлення.

### 3.1 Самокорекція — методологічна помилка в діагностиці

Спершу заявлено «234 рази» — це порахований загальний рядок `could not serialize access due to concurrent update` по **всій** системі, без звірки яких SQL-запитів він стосується. Розклад показав що переважна більшість — інші, не пов'язані гонки (`sale_order` якісні картки дітей, `discuss_channel_member` UI-стан читання, `mail_notification`, `zadarma_call`).

**Реальна кількість саме цього бага** [`zgrep` по всіх логах 05.07–19.07]: **4 випадки**, усі Instagram:
- 2026-07-07 11:51:22 — channel_id=903 — Margarita Yakovleva
- 2026-07-13 12:46:55 — channel_id=937 — natali💛💙natali
- 2026-07-17 07:08:42 та 08:58:47 — channel_id=951 — Ljudmyla Fedyna Komarnytska (2×)

Жоден з цих чотирьох не пояснює оригінальний приклад (Alevtyna/Telegram — п.2, хибна тривога).

## 4. Ground-truth перевірка + друга методологічна помилка

`sendpulse.webhook.data` зберігає сирий payload КОЖНОГО вебхука (7-денний ретеншен на момент перевірки) — це найближче до «що SendPulse реально надіслав». Перший чорновий запит (LEFT JOIN за `contact_id`+2хв вікно, GROUP BY день/канал, `count(*) FILTER`) показав тривожні цифри — напр. 13.07 telegram: **298 вебхуків проти 86 повідомлень**.

**Це виявилось артефактом join-фанауту**: контакт з кількома повідомленнями в одному 2-хвилинному вікні множив рядки в JOIN ДО GROUP BY, роздуваючи `count(*)`. Перевірка напряму (`SELECT count(*) ... WHERE service='telegram' AND date='2026-07-13'`) показала **85** реальних вебхуків, не 298 — і всі 85 мали пару.

Коректний запит — **`NOT EXISTS`-кореляція рядок-в-рядок**, без JOIN:

```sql
SELECT wd.id FROM sendpulse_webhook_data wd
WHERE wd.event_type='incoming_message'
  AND NOT EXISTS (
    SELECT 1 FROM sendpulse_message sm
    WHERE sm.sendpulse_contact_id = wd.sendpulse_contact_id
      AND sm.direction='incoming'
      AND sm.date BETWEEN wd.create_date - interval '2 minutes' AND wd.create_date + interval '2 minutes'
  )
```

За 7-денне вікно: **11 нез'єднаних рядків, усі — коментарі під Instagram/Facebook постами** (`media_product_type=FEED` або `item=comment,verb=add`), які код навмисно маршрутизує в `_process_comment_event` (окрема модель), а не в `sendpulse.message`. Це не втрата, а нормальна поведінка.

**Висновок:** за 7-денне ground-truth вікно — жодної ДОДАТКОВОЇ непоясненої втрати понад ті 4 випадки з п.3.

## 5. SendPulse API — чи можна перевірити ще?

Перевірено живою OpenAPI-специфою SendPulse (`api.sendpulse.com/.well-known/openapi/{telegram,chatbots}.yaml`, не здогадками URL):
- **Telegram service API** (26 шляхів) — жодного message-history ендпоінту.
- **Chatbots service API** — лише 3 шляхи: `GET /dialogs`, `GET /account`, `GET /bots`. `/dialogs` дає **останнє** повідомлення (не історію) по всіх діалогах, без фільтра contact/дата — лише пагінація `size/skip/search_after/order`.

Повного pull-API історії повідомлень у SendPulse немає — розширено використано те, що є (`/dialogs`, п.7.3).

## 6. Застосовані фікси

| Версія | Коміт | Що |
|---|---|---|
| v17.0.15.3 | `d6f89a3` | `_update_partner_source`: `cr.savepoint()` навколо конкретного `UPDATE message_count`; контролер повертає HTTP 500 замість завжди-200 |
| v17.0.15.4 | `e068e2b` | `sendpulse.webhook.data` ретеншен 7→30 днів (для майбутніх аудитів) |
| v17.0.15.5 | `f892bcc` | `cr.savepoint()` навколо **всієї** обробки події в контролері (не лише message_count) — audit-запис переживає БУДЬ-ЯКИЙ збій обробки |
| v17.0.15.6 | `669c6f6` | `cron_check_message_gap` — щоденний крон, звіряє webhook_data↔sendpulse.message (NOT EXISTS, з виключенням коментарів), Telegram-алерт на розрив |
| v17.0.15.7 | `d9efab9` | `cron_check_dialogs_snapshot` — другий незалежний шар: live `GET /dialogs`, звірка `last_inbox_message` |
| v17.0.15.8 | `c25b962` | Той самий клас бага в `controllers/meta_lead_webhook.py::handle_leadgen` (знахідка окремого Odoo/OCA-аудиту, розд. 7) — `cr.savepoint()` навколо кожного `entry` в multi-lead payload |

## 7. Побічні знахідки

### 7.1 Секрет-витік
Під час діагностики (широкий `SELECT ... WHERE key LIKE 'omnichannel_bridge%'`, без фільтра password-полів) у чат випадково потрапили `telegram_bot_token` і `openai_api_key` (Gemini). **Обидва варто вважати скомпрометованими і ротувати** — окремо від цього інциденту, статус підтвердження ротації невідомий.

### 7.2 Odoo/OCA-аудит модуля (делеговано агенту, 19.07.2026)
Повний код-рев'ю `odoo_chatwoot_connector` на відповідність рівню Odoo 17 / OCA. Топ-5 знахідок:
1. 🔴 `sendpulse_connect.py` = 5486 рядків, ~14 різних логічних відповідальностей в одному класі — God Object.
2. 🔴 `meta_lead_webhook.py` без savepoint — **виправлено, п.6, v17.0.15.8**.
3. 🟡 `sendpulse_connect.py:3840,3871,3883` — `except Exception: pass` без логування навколо відправки повідомлень клієнту.
4. 🔴 `__manifest__.py depends` не містить `loyalty`/`sms`, хоча код їх реально використовує (`loyalty.program`, `sms.sms`) — install/upgrade працює лише через транзитивність.
5. 🟡 Дубльований патерн "sendpulse.message → message_post → partner.sendpulse.message" незалежно в 3 місцях, без спільного helper.

Повний звіт — у сесійній пам'яті (`/project_sendpulse_message_loss_savepoint_fix_2026-07-19.md`), не перенесено сюди повністю (репо не для внутрішньої build-документації Fayna).

### 7.3 /dialogs API — обмеження
`GET /chatbots/dialogs` не має фільтра по `contact_id`/даті — лише пагінація. `cron_check_dialogs_snapshot` (п.6) тому бере тільки 100 найсвіжіших (`order=desc`), не всю історію — це свідоме обмеження, не недогляд.

## 8. Що НЕ виправлено (відкрито)

1. **58 випадків невдалої ВІДПРАВКИ** відповіді менеджера клієнту (SendPulse 422: текст >512 символів АБО WhatsApp/Messenger 24h-вікно закрилось) — інший клас втрати (клієнт не отримує відповідь оператора), виявлено 19.07, не пофіксовано.
2. **Відновлення вже втраченого** (4 випадки з п.3) — неможливе автоматично (в Odoo нічого не лишилось, транзакція відкотилась повністю). Єдиний шлях — ручна звірка в SendPulse-дашборді для 3 названих клієнтів навколо точного часу інциденту.
3. **God Object рефакторинг** `sendpulse_connect.py` (аудит п.7.2.1) — велика окрема робота, не в межах цього інциденту.
4. **`except Exception: pass`** без логування (аудит п.7.2.3), **`depends` у manifest** (аудит п.7.2.4), **дублювання коду** (аудит п.7.2.5) — окремі задачі з Odoo/OCA-аудиту.

## 9. Деплой

- ✅ Локал → GitHub (`main`) — усі коміти вище.
- ✅ **Staging** (`staging-campscout`) — задеплоєно і звірено (git-хеші local=origin=staging).
- ⏳ **Прод** (`campscout`) — чекає окремого підтвердження (пайплайн #4ZONES: Mac→GitHub→staging→prod).

## 10. Урок

Одна Odoo-транзакція на HTTP-request + raw SQL без savepoint на будь-якій, навіть некритичній операції всередині webhook-обробника = тихо забирає з собою критичні дані при найменшому винятку. Патерн `cr.savepoint()` навколо ризикованих під-операцій — вже мав прецедент у цьому репо (коміт `0fa8c20`, consent-log) до цього інциденту; тепер застосований системно в обох вебхук-контролерах модуля (SendPulse + Meta leads). Вартий переносу як стандартна практика на будь-який майбутній webhook-хендлер: **кожен незалежний под-крок обробки — свій savepoint, інакше один збій за визначенням стирає все, що було до нього в тій самій транзакції.**

Другий урок — методологічний: діагностичний SQL з JOIN + `count(*)` на неунікальному ключі (contact_id+часове вікно) даватиме фанаут-артефакти. Для перевірки «є X без Y» — завжди `NOT EXISTS`-кореляція рядок-в-рядок, ніколи LEFT JOIN + GROUP BY на пошук відсутності.

---
*Пов'язано: [CHANGELOG.md](../CHANGELOG.md) v17.0.15.3–15.8 · [INDEX.md](INDEX.md)*
