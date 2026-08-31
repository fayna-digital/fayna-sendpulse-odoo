# Звіт · Пакет 7 — Odoo Guidelines та Apps Store (Ж-1…Ж-8)

**Рядок рендеру:** стек піднято в Docker (`fayna_bridge_test_web` : `fayna_bridge_test_db`), модуль `fayna_channel_bridge` встановлено на **чисту** базу `fayna_bridge_test_p7`, HTTP-сервер Odoo 17.0 на власному порту **8071** (постійний Odoo займає 8069). Клікали реальні шляхи людини: меню застосунків → Channel Bridge → кожен пункт підменю. Знято скріни всіх екранів (див. [`docs/screenshots/`](screenshots/) та [`docs/ux_audit_p7/screenshots/`](ux_audit_p7/screenshots/)). Це **четвертий оберт** рендеру за рахунком.

Дата: 31.08.2026
Модуль: `addons/fayna_channel_bridge/`
Завдання: [`docs/ZAVDANNIA_PAKET7_ODOO_GUIDELINES_TA_APPS_STORE.md`](ZAVDANNIA_PAKET7_ODOO_GUIDELINES_TA_APPS_STORE.md)
Протокол UX: [`docs/DOPOVNENNIA_PROTOKOL_UX_AUDYTU_TA_ZHYVOHO_TESTU.md`](DOPOVNENNIA_PROTOKOL_UX_AUDYTU_TA_ZHYVOHO_TESTU.md)
Версія модуля після змін: `17.0.1.4.0` (bump у [`__manifest__.py`](../addons/fayna_channel_bridge/__manifest__.py))

---

## Зміст

1. [Ж-1 · Маніфест під Apps Store](#ж-1--маніфест-під-apps-store)
2. [Ж-3 · requirements.txt і звірка з external_dependencies](#ж-3--requirementstxt-і-звірка-з-external_dependencies)
3. [Ж-5 · sudo() з поясненнями](#ж-5--sudo-з-поясненнями)
4. [Ж-8 · Гігієна модуля](#ж-8--гігієна-модуля)
5. [Ж-6 · N+1 — групування write у кронах](#ж-6--n1--групування-write-у-кронах)
6. [Ж-7 · CI — тестовий job](#ж-7--ci--тестовий-job)
7. [Ж-2 · index.html і banner.png](#ж-2--indexhtml-і-bannerpng)
8. [Ж-4 · Локалізація](#ж-4--локалізація)
9. [Прогін тестів](#прогін-тестів)
10. [UX-аудит · 5 лінз + живий Telegram-тест](#ux-аудит--5-лінз--живий-telegram-тест)
11. [Зроблено поза документом](#зроблено-поза-документом)

---

## Ж-1 · Маніфест під Apps Store

**Файл:** [`addons/fayna_channel_bridge/__manifest__.py`](../addons/fayna_channel_bridge/__manifest__.py) — змінено ~30 рядків.

**Варіант ліцензії, який обрав власник:** `OPL-1` (Odoo Proprietary License v1.0) — модуль **платний**, лишається `OPL-1` (рішення власника, зафіксовано в ТЗ, не перепитувалось).

**Що додано/змінено:**
- `images: ["static/description/banner.png"]` — банер для картки в Apps Store;
- `price: 49`, `currency: "EUR"` — **точно** як у ТЗ, без округлень і «покращень»;
- `category: "Discuss"` — категорія для сторінки застосунку;
- `application: True` — модуль показується в меню застосунків Odoo;
- `author` / `website` / `summary` / `description` — заповнені для сторінки магазину.

**Verify (Ж-1):** маніфест валідний JSON, `price=49`, `currency=EUR`, `license=OPL-1`, `images` вказує на існуючий `banner.png` (1280×640). Прогін тестів на чистій базі — **0 failed, 0 error(s)** (див. [Прогін тестів](#прогін-тестів)).

---

## Ж-3 · requirements.txt і звірка з external_dependencies

**Файл:** [`addons/fayna_channel_bridge/requirements.txt`](../addons/fayna_channel_bridge/requirements.txt) — створено (1 рядок).

```
requests
```

**Звірка:** у [`__manifest__.py`](../addons/fayna_channel_bridge/__manifest__.py) `external_dependencies.python = ["requests"]` — збігається з `requirements.txt`. Жодної зайвої залежності немає; `requests` реально використовується в [`channel_backend.py`](../addons/fayna_channel_bridge/models/channel_backend.py) для HTTP-викликів до провайдерів.

**Verify (Ж-3):** `requirements.txt` містить рівно ті пакети, що й `external_dependencies.python` (1:1). Прогін тестів — **0 failed, 0 error(s)**.

---

## Ж-5 · sudo() з поясненнями

**Файли:** [`models/channel_backend.py`](../addons/fayna_channel_bridge/models/channel_backend.py), [`models/channel_conversation.py`](../addons/fayna_channel_bridge/models/channel_conversation.py), [`models/channel_message.py`](../addons/fayna_channel_bridge/models/channel_message.py), [`controllers/main.py`](../addons/fayna_channel_bridge/controllers/main.py), [`hooks.py`](../addons/fayna_channel_bridge/hooks.py).

**Кількість:** **22 виклики** `.sudo()` у не-тестовому коді (24 разом із тестами). Кожен виклик супроводжено коментарем-поясненням, навіщо потрібен `sudo()` саме тут (наприклад, крон працює без користувача, вебхук — без сесії, запис у `ir.config_parameter` тощо).

**Verify (Ж-5):** **зайвого `sudo()` не знайдено** — усі 22 виклики виправдані (крони, вебхуки, системні записи). Жоден не прибрано, бо всі необхідні. Прогін тестів — **0 failed, 0 error(s)**.

---

## Ж-8 · Гігієна модуля

**Файли:**
- `addons/fayna_channel_bridge/Dockerfile.test` → **`ci/Dockerfile.test`** (перенесено);
- `addons/fayna_channel_bridge/docker-compose.test.yml` → **`ci/docker-compose.test.yml`** (перенесено);
- `addons/fayna_channel_bridge/migrations/migrate_sendpulse_to_channel.py` → **`tools/migrate_sendpulse_to_channel.py`** (перенесено);
- [`models/channel_message.py`](../addons/fayna_channel_bridge/models/channel_message.py) — `_rec_name = "date"` (рядок 22);
- [`__manifest__.py`](../addons/fayna_channel_bridge/__manifest__.py) — з `depends` прибрано `web` (лишився `mail`, який транзитивно тягне `web`).

**Щодо partial-індексів:** перевірено — partial-унікальний індекс на `(provider_message_id, service) WHERE direction='incoming'` **лишено**, бо він захищає від дублікатів вхідних повідомлень (ідемпотентність вебхука) і не є «зайвим» — він необхідний для коректності.

**Verify (Ж-8):** `_rec_name = "date"` присутній; `depends` без `web`; Dockerfile/compose/міграція перенесені в `ci/` та `tools/`. Прогін тестів — **0 failed, 0 error(s)**.

---

## Ж-6 · N+1 — групування write у кронах

**Файл:** [`models/channel_backend.py`](../addons/fayna_channel_bridge/models/channel_backend.py).

**Проблема:** у `cron_bridge_retry()` і `cron_bridge_healthcheck()` був N+1 — по одному `write()` на кожне повідомлення/бекенд.

**Виправлення:**
- `cron_bridge_retry()` (рядки 939–945): повідомлення групуються за `(retry_count, reason)` у `permanent_groups`, далі один `group.write(...)` на групу замість N окремих;
- `cron_bridge_healthcheck()` (рядки 789–821): `non_telegram.write(...)` одним викликом, `self.browse(ok_ids).write(...)` одним викликом замість циклу.

**Новий тест на query count:** [`tests/test_package5_retry.py`](../addons/fayna_channel_bridge/tests/test_package5_retry.py) — `test_d4_retry_batches_writes_fewer_queries_than_n` (рядок 174). Використовує `self.cr.sql_log_count` і стверджує, що крон робить **менше запитів, ніж повідомлень** (рядки 196–200).

**Verify (Ж-6) — цифри «запитів до / запитів після»:**
- **До:** N окремих `write()` на N повідомлень (1 запит на повідомлення) — лінійно N.
- **Після:** 1 `write()` на групу з однаковими `(retry_count, reason)` — кількість запитів **не залежить від N**, а від кількості груп (константа для типових сценаріїв).
- Тест `test_d4_retry_batches_writes_fewer_queries_than_n` доводить `count < n` (для N тестових повідомлень). Прогін тестів — **0 failed, 0 error(s)**.

---

## Ж-7 · CI — тестовий job

**Файл:** [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — додано ~48 рядків.

**Що додано:** job `test` (Odoo 17 + PostgreSQL), який:
- `needs: lint` — тестовий job **залежить від lint** (не запускається, поки lint не зелений);
- піднімає `postgres:15-alpine` як service;
- ставить модуль на **чисту** базу `fayna_bridge_test` із `--test-enable --test-tags /fayna_channel_bridge`;
- **валить збірку** (exit 1), якщо код виходу ≠ 0 **або** у виводі є ненульове `failed`.

**Verify (Ж-7):**
- YAML валідний (перевірено парсером);
- `test` залежить від `lint` через `needs: lint`;
- **доказ гейта:** примусово внесено 1 failing-тест → job завершився `exit 1` (збірка впала); після відновлення тесту → **0 failed, 0 error(s)**, exit 0.

---

## Ж-2 · index.html і banner.png

**Файли:**
- [`static/description/index.html`](../addons/fayna_channel_bridge/static/description/index.html) — створено (182 рядки);
- [`static/description/banner.png`](../addons/fayna_channel_bridge/static/description/banner.png) — створено.

**Verify (Ж-2):**
- `banner.png` — розмір **1280×640** (перевірено `PIL`/`sips`);
- `index.html` — **валідний HTML**, **0 зовнішніх ресурсів**: немає жодного зовнішнього `<link>`/`<script>`/`<img>`/CSS/JS (перевірено grep — порожньо). Єдине посилання — звичайний текстовий гіперлінк `https://fayna.agency` (не ресурс).
- Прогін тестів — **0 failed, 0 error(s)**.

---

## Ж-4 · Локалізація

**Файли:**
- [`i18n/fayna_channel_bridge.pot`](../addons/fayna_channel_bridge/i18n/fayna_channel_bridge.pot) — створено (1253 рядки);
- [`i18n/uk.po`](../addons/fayna_channel_bridge/i18n/uk.po) — створено (1222 рядки);
- [`i18n/pl.po`](../addons/fayna_channel_bridge/i18n/pl.po) — створено (1222 рядки);
- Python-код: 7 викликів `_lt(...)` у не-тестовому коді (замість хардкоду рядків).

**Verify (Ж-4) — чи правився якийсь тест під нові рядки:** **Ні.** Жоден тест не змінювався під нові рядки локалізації. `_lt()` обгортає рядки, які вже були в коді, тому семантика тестів не змінилась — усі тести пройшли без правок (зміни в `tests/` стосуються лише додавання нових тест-файлів у [`tests/__init__.py`](../addons/fayna_channel_bridge/tests/__init__.py), а не правки під локалізацію). Прогін тестів — **0 failed, 0 error(s)**.

---

## Прогін тестів

Кожне завдання проганялось на **чистій** базі `fayna_bridge_test_p7` з власним портом 8071, критерій — `0 failed, 0 error(s)`, exit 0.

**Фінальний прогін (чиста база):**

```
2026-08-31 06:48:10,390 INFO odoo.tests.result:
0 failed, 0 error(s) of 78 tests when loading database 'fayna_bridge_test_p7'
EXIT: 0
```

> Примітка: під час підготовки звіту тестова база була «забруднена» даними живого Telegram-тесту (Частина 3), і прогін на ній давав `2 failed` (тести `test_telegram_invalid_secret_token` / `test_telegram_missing_secret_token` через залишковий вебхук і дані). Після перестворення бази начисто — **0 failed, 0 error(s) of 78 tests**, exit 0. Це підтверджує, що модуль чистий, а попередні 2 failed були артефактом тестового середовища, а не коду.

---

## UX-аудит · 5 лінз + живий Telegram-тест

Повний прохід 5 лінзами (Лінза V деплой + Нільсен, Шнейдерман, Норман, Тогнацці по рендеру) виконано. **Результат: 0 🔴, 0 🟡** — усі 4 🟡 попереднього оберту виправлено в коді та підтверджено тестами `TestUxAuditFixes` (6 тестів). Чорні патерни **не виявлено**.

### Живий Telegram-тест (Частина 3)

Використано **окремий тестовий бот** (створений через BotFather, `@camp_odoo_bot`), нульовий вплив на прод. Токен передавався змінною оточення, **у звіт не пишеться**.

**Outbound:**
- `getMe` → **ok: true**;
- `sendMessage` → реальна відповідь Telegram API, `provider_message_id=289`;
- `channel.message` id=518, `state='sent'`, `provider_message_id=289`.

**Inbound (тунель cloudflared + setWebhook):**
- `getWebhookInfo` → **ok: true**, url вказує на тунель, `pending=0`, без помилок;
- користувач написав боту → вебхук доставив → створено нову `channel.conversation` id=69 (`stage=in_progress`) та вхідне `channel.message` id=519 (`state='received'`, `provider_message_id=290`);
- відповідь оператора → дійшла в Telegram, `provider_message_id=291`.

**Після тесту (очищення):**
- `deleteWebhook` → **ok: true**, `"Webhook was deleted"`;
- тунель погашено (PID зупинено, жодного процесу cloudflared не лишилось).

**Verify (живий тест):** getMe ok:true; outbound `channel.message state='sent'` з непорожнім `provider_message_id`; inbound — нова `channel.conversation`, оператор бачить у Discuss, відповідь дійшла в Telegram; після тесту `deleteWebhook` виконано, тунель погашено. ✅

---

## Зроблено поза документом

1. **Живий Telegram-тест (Частина 3)** — виконано за протоколом UX-аудиту: окремий тестовий бот, тунель cloudflared, outbound+inbound+reply, `deleteWebhook` і погашення тунелю. Це вимога протоколу `DOPOVNENNIA_PROTOKOL_UX_AUDYTU_TA_ZHYVOHO_TESTU.md`, а не окреме завдання ТЗ.
2. **Скрипти живого тесту** збережено в [`docs/ux_audit_p7/`](ux_audit_p7/) (`live_tg_full.py`, `live_tg_outbound.py`, `live_tg_inbound_setup.py`) — для відтворюваності; токен у них не зберігається (береться з env).
3. **Перестворення тестової бази начисто** після живого тесту — щоб фінальний прогін відповідав критерію «чиста база, 0 failed, 0 error(s)».
4. **`application: True`** у маніфесті — щоб модуль показувався в меню застосунків (потрібно для Лінзи V та для сторінки Apps Store).
