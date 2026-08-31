# Завдання Етапу 1 — `fayna_channel_bridge` (для зовнішніх моделей)

Джерело: `AUDIT_FAYNA_CHANNEL_BRIDGE_2026-08-30.md` §7, Етап 1.
Репо: `fayna-sendpulse-odoo`, гілка `feature/direct-transport`.
Модуль: `addons/fayna_channel_bridge/` (Odoo 17).

**Загальні правила для виконавця (діють на ВСІ завдання):**

1. Правити лише названий файл. Не чіпати інші, не «покращувати» дотично.
2. Не міняти публічні сигнатури методів, які кличе контролер.
3. Стиль — як у сусідньому коді: докстрінги українською, лапки одинарні
   в цьому модулі, рядок ≤ 100 символів, `ruff check` і `ruff format` чисті.
4. **Жодних AI-підписів**: ні в коді, ні в коментарях, ні в тексті коміту.
   Не згадувати модель, Claude, «generated».
5. Не додавати нових зовнішніх залежностей.
6. Не чіпати `tests/test_operator_end_to_end.py` — це критерій приймання,
   він мусить лишитись без змін і почати проходити САМ.

Критерій приймання всього Етапу 1: тест `T-01`
(`odoo-bin -i fayna_channel_bridge --test-tags /fayna_channel_bridge:TestOperatorEndToEnd`)
**падає зараз** і **проходить після** З-1…З-4.

---

## З-1 · F-02 (P0) · Відповідь оператора падає з `AttributeError`

**Файл:** `addons/fayna_channel_bridge/models/mail_channel.py` (зараз 66 рядків)

**Проблема.** `message_post` кличе два методи, яких у модулі не існує:

- рядок 49: `if self._is_system_message(body_plain):`
- рядок 55: `attachment_url = self._get_attachment_url(attachment_ids[0])`

Перевірено вичерпно: `git grep "def _is_system_message"` по всіх шести гілках
репо (`main`, `feature/direct-transport`, `feature/send-offer-link`,
`chore/astral-toolchain`, `deploy-meta-profile`, `origin/main`) — **нуль**
визначень. Коміт `d3957f3` додав самі виклики.

**Що зробити.** Перенести обидва методи і константу з робочого оригіналу
СТАРОГО модуля — `models/mail_channel.py` у корені репо (не в `addons/`):

- `SYSTEM_MSG_PATTERNS` — рядки 39-48 оригіналу (список regex-шаблонів
  `joined the channel`, `left the channel`, `invited`, `приєднав`, `покинув`,
  `запросив`, `запрошено`);
- `_is_system_message(self, text)` — рядки 229-235 оригіналу;
- `_get_attachment_url(self, attachment_id)` — рядки 237-249 оригіналу.

Перенести **як є за логікою**, з двома правками:
- у `_get_attachment_url` повідомлення логера змінити з `SendPulse Odoo:`
  на `Channel Bridge:` (решта модуля вживає саме цей префікс);
- додати `import re` до наявних імпортів (зараз у файлі є лише `logging`,
  `models`, `html2plaintext`) — без нього `_is_system_message` не працює.

Константу класти на рівні модуля, після `_logger`, як в оригіналі.

**Verify:**
- `grep -c "def _is_system_message\|def _get_attachment_url"` у новому файлі → `2`
- `python3 -m py_compile` — без помилок
- `ruff check` + `ruff format --check` — чисто
- у T-01 зникає `AttributeError`, асерт `'F-02: рівно одне вихідне'` доходить до перевірки

---

## З-2 · F-01 (P0) · Discuss-канали створюються з 0 учасників

**Файл:** `addons/fayna_channel_bridge/models/channel_conversation.py`

**Проблема.** `_create_discuss_channel()` (рядки 367-382) бере учасників так:

```python
partner_ids = [u.partner_id.id for u in self.user_ids if u.active]
if partner_ids:
    channel.add_members(partner_ids=partner_ids)
```

Поле `user_ids` розмови у `create_vals` всередині `_process_incoming_event`
(рядки 203-218) **не заповнюється ніколи**. `channel.backend.user_ids` теж
порожній на проді. Тому список порожній, `add_members` не викликається,
канал лишається без учасників — операторам його не видно.
Доказ із прода (аудит §F-01): `conv 1070..1082 (13 розмов з 27.08) → members = 0`.

**Що зробити.** Розширити добір учасників у `_create_discuss_channel()`
трирівневим падінням, у такому порядку:

1. `self.user_ids` (як зараз) — якщо заповнене;
2. інакше `self.backend_id.user_ids` — оператори, призначені на backend;
3. інакше — усі активні користувачі групи
   `fayna_channel_bridge.group_channel_bridge_officer`.

Брати лише активних користувачів і лише непорожні `partner_id`.
Дублікати partner_id прибрати. Викликати `add_members` один раз готовим списком.

Якщо після всіх трьох рівнів список усе одно порожній — записати
`_logger.warning` з `Channel Bridge:` і id розмови, канал усе одно створити
(не падати).

Групу брати через `self.env.ref(..., raise_if_not_found=False)` і коректно
обробити випадок, коли її нема.

**Verify:**
- у T-01 асерт `assertGreater(members, 0, 'F-01: оператор має бути учасником каналу')` проходить
- `ruff` чисто, `py_compile` чисто

---

## З-3 · F-04 (P0) · Один вебхук створює ДВА рядки журналу

**Файл:** `addons/fayna_channel_bridge/models/channel_conversation.py`

**Проблема.** На один вхідний Telegram-апдейт пишуться два `channel.message`:

1. у контролері — `controllers/main.py`, `Message.create({...})` після
   нормалізації payload, з **правильним** `provider_message_id`
   (напр. `'100'`);
2. у моделі — `channel_conversation.py`, рядок 273,
   `provider_message_id: self._extract_provider_message_id(data, service)`.

Другий пише **порожній рядок**, і ось чому: у модель передається `data=normalized`
(див. `controllers/main.py`, виклик `_process_incoming_event(data=normalized, ...)`),
а `normalized` має лише ключі `service`, `contact`, `bot`, `title`, `date` —
ключа `message` там **немає**. `_extract_provider_message_id` (рядки 314-317)
читає саме `data.get('message')`, отже повертає `''`.

Унікальний індекс має умову `WHERE provider_message_id != ''`, тому порожній
дубль він не ловить. Дедуплікація в контролері теж не ловить — вона відпрацьовує
раніше і шукає за непорожнім id.

**Що зробити.** Прибрати створення `channel.message` з
`_process_incoming_event` — блок `self.env['channel.message'].sudo().create({...})`
(рядки 273-284). Журнал веде контролер, він єдиний має справжній
`provider_message_id`.

**Обов'язково зберегти** те, що йде далі в тому ж `if last_message:` —
пост у `discuss.channel` (рядки 286-298). Тобто прибрати треба саме `create`,
а не увесь блок.

Після цього `_extract_provider_message_id` лишається без викликів — **не видаляти
його** (він знадобиться в Етапі 2 для дедупу інших каналів), але додати
короткий докстрінг-примітку, що метод наразі не використовується.

⚠️ Не чіпати другий `create` у цьому ж файлі, рядок 437 — то **вихідні**
повідомлення, інша гілка.

**Verify:**
- у T-01 асерт `assertEqual(n, 1, 'F-04: один webhook = один рядок журналу')` проходить
- `grep -n "channel.message'\].sudo().create"` по файлу → лишається рівно один (рядок ~437)

---

## З-4 · F-05 (P1) · `partner_id` не заповнюється для нового вхідного

**Файл:** `addons/fayna_channel_bridge/models/channel_conversation.py`

**Проблема.** `_find_partner(self, provider_user_id, email, phone)` (рядки 338-351)
шукає **тільки** за `email` і `phone`. Але Telegram-вебхук у нормалізованому
payload жорстко ставить `'email': ''` і `'phone': ''`
(див. `controllers/main.py`, словник `normalized['contact']`). Instagram і
Messenger так само. Параметр `provider_user_id` у тіло методу не входить узагалі.
Результат із прода: `розмов з 27.08: 13 → partner_id заповнено: 0`.

**Що зробити.** Додати ПЕРШИМ кроком пошук за історією розмов, до email/phone:

- шукати `channel.conversation` з тим самим `provider_user_id`,
  тим самим `service`, у якої `partner_id` заповнений;
- сортувати `write_date desc`, брати `limit=1`, повертати її `partner_id`.

Порядок після правки: `provider_user_id` (історія) → `email` → `phone` → `None`.
Пошук робити через `sudo()`, як решта методу. Виключити з пошуку саму поточну
розмову, якщо метод колись покличуть на існуючому записі.

Логіку email/phone не міняти.

⚠️ **Не додавати нових полів** на `res.partner` і не міняти схему. Пряма
прив'язка «партнер ↔ telegram id» — це окрема вимога Етапу 3, тут її не робити.

**Verify:**
- `py_compile` + `ruff` чисто
- ручний сценарій: розмова з відомим `provider_user_id`, у якої вже є партнер,
  → нова розмова того ж контакту отримує той самий `partner_id`
- T-01 цей асерт не перевіряє — регресії в ньому бути не повинно

---

## З-5 · F-09 (P1) · Мертвий cron, 45 помилок у логу

**Новий файл:** `addons/fayna_channel_bridge/migrations/17.0.1.1.0/post-migrate.py`

⚠️ Наявний `migrations/migrate_sendpulse_to_channel.py` — це окремий ручний
скрипт, **не** Odoo-міграція. Не чіпати його і не класти нове поруч —
Odoo читає лише розкладку `migrations/<версія>/<фаза>.py`.
Версія модуля в `__manifest__.py` вже `17.0.1.1.0`.

**Проблема.** У БД лишився осиротілий запис від попередньої версії:
`ir.cron` 112 «Channel Bridge: Auto-failover перевірка» →
`model.cron_bridge_switch_check()`. Метод перейменували на
`action_switch_all_to_own`, у `data/channel_backend_cron.xml` запису вже немає,
але `noupdate="1"` не дає Odoo прибрати його при оновленні. Падає кожні 30 хв:
`AttributeError: 'channel.backend' object has no attribute 'cron_bridge_switch_check'`.

**Що зробити.** Написати `migrate(cr, version)` (стандартна сигнатура Odoo-міграції),
який:

1. знаходить запис у `ir_model_data` за
   `module='fayna_channel_bridge'` і `name='ir_cron_bridge_switch_check'`;
2. якщо знайдено — видаляє відповідний `ir.cron`, пов'язаний з ним
   `ir.act_server`, і сам рядок `ir_model_data`;
3. якщо не знайдено — тихо виходить (міграція мусить бути **ідемпотентною**:
   повторний запуск не падає).

Працювати через `cr.execute` з параметризованими запитами, БЕЗ f-string у SQL.
Не видаляти нічого за жорстко зашитим числовим id (112 / 1357) — лише за xmlid,
бо на іншій базі id інші.
Залогувати, що саме видалено, через `logging` з префіксом `Channel Bridge:`.

**Verify:**
- `python3 -m py_compile` чисто
- повторний прогін міграції не кидає виняток
- після оновлення модуля на проді `AttributeError: ... cron_bridge_switch_check`
  зникає з `odoo.log` протягом години

---

## З-6 · Зламана сигнатура `post_init_hook` (блокує оновлення модуля)

**Файл:** `addons/fayna_channel_bridge/hooks.py` (незакомічений, 31 рядок)

**Проблема.** Хук оголошено як `def post_init_hook(cr, registry):` і всередині
він сам будує `env = api.Environment(cr, SUPERUSER_ID, {})`. В Odoo 17
завантажувач кличе хук як `hook(env)` — тобто першим аргументом приходить
`Environment`, а не курсор. Оновлення модуля впаде.

**Що зробити.** Перевести на сигнатуру Odoo 17: `def post_init_hook(env):`,
прибрати ручне створення `Environment` і зайві імпорти `SUPERUSER_ID`, `api`,
якщо вони більше не потрібні. Логіку призначення груп зберегти без змін.
`env.ref` викликати з `raise_if_not_found=False` і не падати, якщо групи немає.

Докстрінги у цьому файлі зараз англійською — лишити англійською, не переписувати
(це не предмет завдання).

**Verify:**
- `grep -n "def post_init_hook" hooks.py` → `def post_init_hook(env):`
- `grep -c "api.Environment" hooks.py` → `0`
- `py_compile` + `ruff` чисто

---

## Поза кодом (не давати моделі — це операція на проді)

**Бекфіл після З-1…З-4:** додати операторів у 13 наявних каналів
(conv 1070…1082) і зачистити 19 порожніх дублів `channel.message`
(`provider_message_id = ''`). Робиться на проді після того, як фікси заллються
і T-01 стане зеленим. Потребує окремого рішення власника.
