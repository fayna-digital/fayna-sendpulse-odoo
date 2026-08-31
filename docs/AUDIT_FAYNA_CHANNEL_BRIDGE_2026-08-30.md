<!-- #ОК-САМ — аналітичний документ (аудит), не код. Канон 2026-08-19: читання/аналіз без запису коду робиться напряму. -->

# Аудит модуля `fayna_channel_bridge` — 30.08.2026

> Глибокий інженерний аудит модуля, встановленого на прод CampScout 26.08.2026
> замість знятого SendPulse-модуля. Перевірено: працездатність на проді (БД, логи,
> вебхуки), відповідність вимогам Odoo 17, безпека, повнота документації.
>
> **Метод:** прямі запити до прод-БД `campscout`, `odoo.log`, nginx access-log,
> md5-звірка прод-коду з локальним, повне читання 1947 рядків коду модуля,
> перевірка сигнатур проти вихідників Odoo 17 у прод-контейнері.

---

## 0. Резюме для рішення

Модуль **приймає вхідні, але не працює як робочий інструмент**: повідомлення
надходять і зберігаються, проте їх ніхто не бачить, а відповісти на них
технічно неможливо. Обидві причини — окремі дефекти, кожен з яких сам по собі
блокує роботу.

| Статус | Що саме |
|---|---|
| ✅ Працює | Прийом Telegram, Instagram; запис у `channel.conversation` / `channel.message`; створення Discuss-каналу; ідемпотентність по реальному `provider_message_id`; міграція 1069 історичних розмов із SendPulse |
| 🔴 Не працює | Оператори не бачать чатів (0 учасників у каналах); відповідь оператора падає з `AttributeError`; прив'язка до картки клієнта для нового вхідного; мульти-акаунтність (FB-сторінки, IG-акаунти); Viber, TikTok, Facebook — не налаштовані взагалі; вихідні Meta без токенів |
| 🔴 Небезпечно | 5 із 7 вебхуків приймають дані з інтернету **без жодної автентифікації**; bot-токени в URL, у nginx-логах, в `odoo.log` щогодини і plaintext у БД; доступ до токенів має група Officer |
| 🔴 Немає | ТЗ на модуль (наявний `docs/TZ.md` описує старий SendPulse-модуль); UI для розмов і журналу; i18n; `index.html`; тести не виконувались |

**Бізнес-наслідок, зафіксований на 30.08.2026:** з 27.08 надійшло 13 звернень,
серед них про повернення коштів («В мене чоловік в лікарні, мені дуже терміново
потрібні гроші», «Дайте телефон вашого керівника»). Відповідей — **0**.

---

## 1. Що встановлено на проді

| Параметр | Значення | Джерело |
|---|---|---|
| Модуль | `fayna_channel_bridge`, `state=installed`, `latest_version=17.0.1.0.0` | `ir_module_module` |
| Дата установки | 2026-08-26 23:24:51 | `ir_module_module.write_date` |
| `omnichannel_bridge` | `uninstalled` — інший репо (`platforms/omnichannel-bridge`), до справи не стосується | `ir_module_module` |
| Шлях | `/opt/campscout/custom-addons/fayna_channel_bridge` | `docker inspect` mounts |
| Git на проді | **відсутній** — `fatal: not a git repository` | `git log` у каталозі |
| Звірка коду | md5 усіх 17 файлів = локальний закомічений стан | `md5sum` ↔ `md5 -r` |

### 1.1 🔴 #4ZONES порушено

Модуль **залито копіюванням**, а не `git pull`. Каталог на проді не під git,
тому: неможливо сказати «прод = коміт X», неможливо відкотитись, наступний
деплой затре або продублює зміни. Це прямо суперечить `CLAUDE.md` цього репо
і `.cursor/rules/deployment-workflow-critical.mdc`.

### 1.2 Дрейф локального стану

Гілка `feature/direct-transport`, у `main` не влита. Незакомічено:
`__manifest__.py` (bump `1.0.0 → 1.1.0`), нові `hooks.py` і
`tests/test_security_groups.py`. **Ці незакомічені зміни містять дефект,
що зламає установку** — див. F-07.

---

## 2. Критичні дефекти (P0) — прод не працює

### F-01 🔴 P0 · Discuss-канали створюються без жодного учасника

```
conv 1070..1082 (13 розмов з 27.08) → members = 0   ← усі до одної
channel_conversation_res_users_rel → 0 рядків
channel_backend_res_users_rel      → 0 рядків
```

**Причина.** `channel_conversation._create_discuss_channel()` додає в канал
`self.user_ids`. Поле `user_ids` розмови ніколи не заповнюється: у `create_vals`
всередині `_process_incoming_event` його немає. `channel.backend.user_ids`
(оператори каналу) теж порожній і нікуди не проростає.

```python
partner_ids = [u.partner_id.id for u in self.user_ids if u.active]
if partner_ids:
    channel.add_members(partner_ids=partner_ids)   # ← ніколи не виконується
```

**Наслідок.** Канал існує, повідомлення в ньому є, але він не з'являється в
Discuss у жодного користувача. Вхідні надходять «у порожнечу».

**Фікс.** Успадкувати операторів з `backend_id.user_ids` при створенні розмови;
за відсутності — fallback на групу `group_channel_bridge_officer`. Плюс
одноразовий бекфіл для 13 наявних каналів.

---

### F-02 🔴 P0 · Відповідь оператора падає з `AttributeError`

`models/mail_channel.py` в override `message_post` викликає два методи:

```python
if self._is_system_message(body_plain):        # рядок 49
    ...
attachment_url = self._get_attachment_url(attachment_ids[0])   # рядок 55
```

**Жоден із них не визначений.** Файл довжиною 66 рядків визначає лише
`_html_to_text`. Перевірено вичерпно:

| Де шукав | Результат |
|---|---|
| `fayna_channel_bridge/**/*.py` | лише виклики, визначень немає |
| усі аддони на проді (`/opt/campscout/custom-addons`, `/opt/campscout/addons`) | 0 збігів |
| ядро Odoo 17 (`/usr/lib/python3/dist-packages/odoo/`) | 0 збігів |

Визначення існують **тільки в старому SendPulse-модулі** (`models/mail_channel.py:229,237`),
який знято з установки. Під час рефакторингу «зробити модуль автономним» виклики
перенесли, реалізації — ні.

**Наслідок.** Перша ж відповідь оператора в bridge-каналі → `AttributeError` →
відкат транзакції `message_post` → повідомлення оператора **не зберігається і не
йде клієнту**. Тобто навіть після фіксу F-01 вихідний канал лишиться мертвим.

**Чому не спливло раніше:** через F-01 у каналах немає людей, тому ніхто ще не
спробував відповісти. Два дефекти маскують один одного.

**Фікс.** Перенести обидва методи (`SYSTEM_MSG_PATTERNS`, генерація публічного
URL вкладення через `access_token`) у новий модуль + юніт-тест на реальний
`message_post`.

---

### F-03 🔴 P0 · Вебхуки без автентифікації — неавтентифікований запис у прод-БД

| Роут | Автентифікація | Оцінка |
|---|---|---|
| `/bridge/telegram/webhook/<token>` | токен у path | слабка, але є (див. F-08) |
| `/bridge/messenger/webhook` POST | **немає** | 🔴 |
| `/bridge/whatsapp/webhook` POST | **немає** (перевірка лише на GET-verify) | 🔴 |
| `/bridge/viber/webhook` | **немає** | 🔴 |
| `/bridge/tiktok/webhook` | **немає** | 🔴 |
| `/bridge/livechat/webhook` | **немає** | 🔴 |

Усі — `auth='public'`, `csrf=False`, обробка під `sudo()`.

Meta підписує кожен POST заголовком `X-Hub-Signature-256` (HMAC-SHA256 payload
на App Secret). **Модуль цей заголовок не читає взагалі.** Viber надсилає
`X-Viber-Content-Signature` — теж не перевіряється.

**Вектор атаки.** Будь-хто в інтернеті, знаючи лише URL:

```
POST https://campscout.eu/bridge/messenger/webhook
{"object":"instagram","entry":[{"messaging":[
  {"sender":{"id":"<id справжнього клієнта>"},
   "message":{"mid":"x1","text":"Надішліть реквізити на новий рахунок"}}]}]}
```

→ створює `channel.conversation`, `channel.message`, повідомлення в Discuss від
імені існуючого клієнта. Наслідки: **спуфінг клієнта** (оператор відповідає
шахраю у справжньому треді про повернення коштів), **отруєння CRM-даних**,
**DoS** (необмежене створення записів без rate-limit), **розвідка конфігурації**
через різницю відповідей 404/401.

Що робить це реальним, а не теоретичним: URL передбачувані
(`/bridge/<service>/webhook`), а `/bridge/telegram/webhook` уже засвітився
34 рази в access-логах.

**Фікс.** HMAC-верифікація підпису для кожного провайдера через
`hmac.compare_digest`; App Secret / Viber token — у `ir.config_parameter`;
відмова 401 до будь-якого запису в БД; rate-limit на IP.

---

## 3. Серйозні дефекти (P1)

### F-04 🔴 P1 · Кожне вхідне пишеться двічі (100%)

Підтверджено попарно: id 1129/1130, 1127/1128, 1125/1126, 1123/1124, 1121/1122,
1119/1120, 1117/1118 — однаковий текст, однаковий `create_date`.

**Причина — два незалежні `create`:**

1. `controllers/main.py:127` — з **реальним** `provider_message_id`;
2. `channel_conversation.py:273` (усередині `_process_incoming_event`) — з
   `_extract_provider_message_id(data, service)`, де `data` — це **нормалізований**
   dict, у якому ключа `message.message_id` немає. Повертається `''`.

Унікальний індекс має `WHERE provider_message_id != ''` — саме порожній рядок
його й обходить:

```sql
CREATE UNIQUE INDEX channel_message_incoming_provider_uniq
  ON channel_message (provider_message_id, service)
  WHERE direction='incoming' AND provider_message_id IS NOT NULL
    AND provider_message_id != ''      -- ← дірка
```

**Наслідок.** Журнал удвічі більший за реальність; будь-яка аналітика по каналах
завищена вдвічі; ідемпотентність, заявлена в docstring моделі, фактично не діє
для другого шляху. У Discuss дубля немає (`message_post` викликається один раз).

**Фікс.** Прибрати запис у журнал з `_process_incoming_event` — контролер уже
все записав; журналювання має бути в одному місці. Плюс одноразове чищення
9 telegram + 9 instagram + 1 messenger дублів.

---

### F-05 🔴 P1 · Прив'язка до картки клієнта не працює для нового вхідного

```
розмов з 27.08: 13   →   partner_id заповнено: 0
```

`_find_partner(provider_user_id, email, phone)` шукає **тільки** за `email` і
`phone`. Telegram, Instagram, Messenger у вебхуку ні email, ні телефону не
передають — у нормалізованому payload вони жорстко `''`. Пошуку за
`provider_user_id` немає, хоча саме цей ідентифікатор і є єдиним ключем.

Старі 997 розмов мають партнерів лише тому, що їх приніс міграційний скрипт із
SendPulse-даних.

Побічний симптом того самого кореня: у `_process_incoming_event` для посту в
Discuss автор шукається окремо — `res.partner.search([('name','=',contact_name)])`
— тобто **за точним збігом імені**. Це і ненадійно (омоніми, емодзі в імені:
«VIKTORIIA 💖»), і не записується назад у `conv.partner_id`. Два різні механізми
пошуку партнера, обидва неправильні.

**Фікс.** Матчинг за `provider_user_id` через окрему модель ідентичностей
(`channel.identity`: partner ↔ service ↔ provider_user_id), з fallback на
email/phone і ручним wizard-прив'язуванням оператором. Результат писати в
`conv.partner_id` і використовувати як автора повідомлення.

---

### F-06 🔴 P1 · Meta: `return` усередині циклу губить решту пакета

```python
for entry in entries:
    for messaging in entry.get('messaging') or []:
        ...
        except Exception:
            return self._json({...}, status=500)   # ← вихід з усього обробника
```

Meta надсилає **пакетами**: `entry[]` × `messaging[]`. Помилка на одному
повідомленні перериває обробку решти. Ті, що вже створені, при ретраї
відсіються дедупом, а решта пакета не обробиться ніколи — Meta ретраїть той
самий пакет, він падає в тому ж місці.

Додатково: відповідь **HTTP 500** провайдеру вмикає його механізм ретраїв. При
стійкій помилці — нескінченний цикл ретраїв і навантаження на прод. Канон для
webhook-приймачів: **завжди 200** після успішної валідації підпису, а помилки
обробки — у чергу/лог, не в HTTP-код.

---

### F-07 🔴 P1 · `post_init_hook` зі старою сигнатурою зламає установку

`hooks.py` (незакомічений, локально):

```python
def post_init_hook(cr, registry):   # ← сигнатура Odoo ≤15
```

Перевірено проти вихідників Odoo 17 у прод-контейнері,
`odoo/modules/loading.py:245-247`:

```python
post_init = package.info.get('post_init_hook')
    getattr(py_module, post_init)(env)      # ← один аргумент: env
```

**Наслідок.** `TypeError: post_init_hook() missing 1 required positional
argument: 'registry'` при `-i`/`-u` версії 1.1.0. Прод зараз живий тільки тому,
що на ньому 1.0.0 без хука. **Наступний деплой у поточному вигляді покладе
оновлення модуля.**

Окремо: сам підхід «хук роздає групи всім `base.group_system`» — обхід моделі
прав Odoo. Видимість меню розв'язується `groups` на `menuitem` (уже є) плюс
явним призначенням груп; масова роздача прав на модель, що містить токени,
розширює поверхню витоку.

---

### F-08 🔴 P1 · Секрети: у URL, у логах, plaintext у БД, доступні Officer

Чотири незалежні канали витоку одного й того самого bot-токена:

1. **URL вебхука** — `/bridge/telegram/webhook/<повний bot-токен>`.
   `grep -c "bridge/telegram/webhook" /data/logs/proxy-host-6_access.log` → **34**.
   Токен у path потрапляє в access-логи nginx, у ротовані `.gz`, у Referer, у
   будь-який проміжний проксі.
2. **`odoo.log`** — healthcheck-cron **щогодини** друкує
   `Channel Bridge: Telegram webhook set to https://…/<токен>`
   (`channel_backend.py:616`). Лог `odoo.log` = 28.5 МБ, читається ширшим колом.
3. **БД plaintext** — `bot_token`, `webhook_secret`, `credentials` — звичайні
   `varchar`/`text`. Docstring-и обіцяють «зберігається зашифровано»
   (`channel_backend.py:36,88,94`) — шифрування в коді **немає взагалі**:
   `grep -rn "encrypt\|Fernet\|cipher"` → 0 збігів. Це не просто дефект, це
   **неправдива гарантія в документації**, на яку спираються при оцінці ризику.
4. **Права** — група `Officer` має `perm_read` на `channel.backend`, а `ir.rule`
   `rule_channel_backend_officer` дає доступ до записів з `user_ids = False`,
   тобто **до всіх** (`channel_backend_res_users_rel` порожній). `password="1"`
   на полі `bot_token` маскує лише у формі — RPC `read()` віддає значення.
   Поле `credentials` (JSON з Meta/WhatsApp токенами) не приховане навіть у формі.

Плюс `_find_backend_by_token` порівнює токен через `==`, а не
`hmac.compare_digest` — теоретично timing-вразливо.

**Фікс (у цьому порядку, ротація — після).** Telegram підтримує штатний
`secret_token` у `setWebhook`, який приходить заголовком
`X-Telegram-Bot-Api-Secret-Token` — це і є канонічна заміна токена в URL. Далі:
непередбачуваний opaque-path замість токена; прибрати токен з усіх лог-рядків;
секрети — у `ir.config_parameter` з обмеженим читанням або шифрувати ключем
з `odoo.conf`; звузити `ir.rule` для Officer; поле `credentials` закрити
через `groups=` на рівні поля.

> **Ротація токенів — окремим кроком після того, як контур запрацює на 100%
> (рішення власника, 30.08.2026).** Ротація до фіксу дизайну безглузда: новий
> токен ляже в ті самі логи протягом години.

---

### F-09 🟠 P1 · Мертвий cron — 45 помилок з моменту переходу

```
ir.cron 112 «Channel Bridge: Auto-failover перевірка» → model.cron_bridge_switch_check()
AttributeError: 'channel.backend' object has no attribute 'cron_bridge_switch_check'
```

Метод перейменували на `action_switch_all_to_own`, а XML-запис
`ir_cron_bridge_switch_check` лишився в `ir_model_data` від попередньої версії.
У `data/channel_backend_cron.xml` його вже немає, але `noupdate="1"` не дозволяє
Odoo прибрати його при оновленні. Падає кожні 30 хв, **45 разів** у логу.

**Фікс.** Migration-скрипт `post-migrate`, що видаляє осиротілий `ir.cron` +
`ir.act_server` за xmlid.

---

## 4. Архітектурні обмеження — те, чого вимагає власник

### F-10 🔴 P1 · Один акаунт на канал. Кілька FB-сторінок / IG-акаунтів неможливі

Вимога власника: багато FB-сторінок, два TG-боти, кілька IG-акаунтів, WhatsApp,
Viber, TikTok — усі одночасно, вхідні й вихідні.

Що є зараз:

```python
def _find_backend_by_service(self, service):
    return Backend.search([('service','=',service), ('provider','=','direct'),
                           ('active','=',True)], limit=1)     # ← limit=1
```

Meta надсилає id сторінки в `entry[].id` — саме для розрізнення акаунтів.
**Модуль це поле повністю ігнорує.** Дві FB-сторінки → обидві падають в один
backend, і відповідь піде токеном першої (або не піде зовсім). Те саме для
кількох IG-акаунтів.

Unique-індекс `(service, provider, COALESCE(bot_id,''))` розрахований на
розрізнення за `bot_id`, але `bot_id` заповнюють **тільки для Telegram** — тому
два TG-боти справді працюють (backend 1 і 6), а Meta-акаунти — ні.

**Фактичний стан каналів на проді:**

| Канал | Backends | Креденшели | Останнє вхідне | Вихідні |
|---|---|---|---|---|
| Telegram | 2 | `bot_token` є | 29.08 07:06 | можливі |
| Instagram | 1 | **немає** | 29.08 19:08 | **неможливі** |
| Messenger | 1 | **немає** | 27.08 09:34 | **неможливі** |
| WhatsApp | 1 | є (337 б) | 25.08 (до переходу) | теоретично |
| Facebook (сторінки) | **0** | — | — | — |
| Viber | **0** | — | — | — |
| TikTok | **0** | — | — | — |

`_meta_send_single` без `access_token` одразу повертає
«Meta Page Access Token не налаштований» — тобто **відповісти в Instagram і
Messenger сьогодні фізично неможливо**, навіть якби оператор бачив чат.

**Фікс.** Маршрутизація Meta-вебхука за `entry[].id` → `channel.backend` з
`page_id`/`ig_business_id`; зняти `limit=1`; unique-ключ перевести на
`(service, provider, account_id)`, де `account_id` — універсальний ідентифікатор
акаунта (page_id / ig_id / bot username / viber bot id).

---

### F-11 🔴 P1 · Немає OAuth-онбордингу; вимога не була записана в ТЗ

Вимога власника: «інсталюється модуль → кнопка «Підключити Facebook» → логін →
дозвіл на сторінки → сторінки підтягуються самі». Без ручного пошуку токенів і
налаштування вебхуків.

Що є зараз: підключення каналу = зайти в Meta Business Suite, згенерувати Page
Access Token, вставити JSON у текстове поле `credentials`. Рівно те, чого
власник не хоче. У модулі немає ні `app_id`/`app_secret`, ні redirect-контролера,
ні обміну code→token, ні виклику `/me/accounts` для переліку сторінок.

**Важливо: це не з нуля.** OAuth уже написаний — у знятому SendPulse-модулі:
`models/sendpulse_oauth.py`, `models/meta_profile.py`,
`controllers/meta_oauth.py`, `models/sendpulse_facebook_page.py` (multi-page
state). Під час рефакторингу «автономний модуль» цей шар не переїхав.

**Причина, чому вимогу «не реалізовано»: її ніде не записано.** ТЗ на
`fayna_channel_bridge` не існує — див. F-20.

---

## 5. Дефекти реалізації (P2)

### F-12 🟠 LiveChat-обробник впаде завжди — колізія ключа `event`

```python
event = data.get('event', '')      # 'incoming_event'  (str)
if event != 'incoming_event': ...
evt = data.get('event') or {}      # той самий str, не dict
text = (evt.get('text') or {})     # AttributeError: 'str' has no attribute 'get'
```

Docstring сам показує неможливий payload з двома ключами `event`:
`{"event": "incoming_event", "chat": {...}, "event": {...}}`. Обробник ніколи не
працював і не міг бути протестований.

### F-13 🟠 Фальшивий healthcheck

`cron_bridge_healthcheck` для всіх не-Telegram каналів безумовно пише
`last_healthcheck_ok = True`, нічого не перевіряючи («інші канали — поки no-op»).
Тому на проді Instagram, Messenger і WhatsApp показують ✅ **зелений статус, не
маючи навіть токенів**. Це гірше за відсутність healthcheck: він активно
дезінформує.

### F-14 🟠 `channel.message` не пов'язаний з `channel.conversation`

У моделі немає `conversation_id`. Журнал прив'язаний лише до `backend_id` і
текстового `provider_user_id`. Наслідок: історію конкретної розмови не дістати
ORM-зв'язком, тільки збіркою по рядковому полю; неможливий `One2many` на формі
розмови; каскадне видалення/анонімізація (RODO) не працює по розмові.

### F-15 🟠 Час повідомлення втрачається

`channel.message.date` має `default=fields.Datetime.now`, і жоден контролер не
передає `date` у `create`. Telegram дає `message.date`, Meta — `timestamp`,
Viber — `timestamp`; усі три парсяться в `timestamp_ms` **і не використовуються**
для запису. Тому `date` = час обробки, а не час відправлення клієнтом. При
затримці/ретраї порядок повідомлень спотвориться (`_order = 'date asc'`).

### F-16 🟠 Дедуп по порожньому `provider_message_id` дає хибний «дубль»

`_process_incoming` шукає `('provider_message_id','=',provider_message_id)` без
перевірки на порожнечу. Якщо провайдер не дав id (Viber `message.token` буває
відсутній), пошук по `''` знайде **будь-який** попередній запис із порожнім id
і мовчки поверне «duplicate, skipping» — справжнє повідомлення клієнта
загубиться без сліду в логах рівня ERROR.

### F-17 🟠 `cron_bridge_retry` без обмежень

`search(...)` без `limit`, синхронні HTTP-виклики в циклі по всіх failed без
таймауту на весь прохід. При накопиченні відмов cron-воркер зависне; на проді
крон стоїть кожні 15 хв і може накластися сам на себе.

### F-18 🟠 RODO: повний payload з PII без маскування і без ретенції

`channel_message.raw_json` зберігає **весь** вхідний payload
(`json.dumps(data)`) — тексти клієнтів, їхні id, імена, посилання на вкладення.
Маскування немає (у знятому модулі був `omni_pii_mask`). Cron архівації чистить
`channel.conversation`, але `channel.message` **не чіпає** — тобто політика
30 днів на журнал не поширюється. Для дитячих таборів (дані неповнолітніх) це
окремий ризик.

### F-19 🟡 Guard вихідних перевіряє тільки `message_type`

`message_post` override пропускає в транспорт усе, що не
`notification`/`auto_comment`. Підтип не перевіряється — будь-який код, що
запостить у канал повідомлення з підтипом `mail.mt_note` (внутрішня нотатка),
відправить його клієнту. У чистому Discuss-каналі UI нотаток немає, тож живого
витоку зараз не видно, але захист має спиратися на підтип, а не на тип.

---

## 6. Документація і відповідність стандарту Odoo

### F-20 🔴 ТЗ на модуль не існує

`docs/TZ.md` — це ТЗ **старого SendPulse-модуля**: «omnichannel-міст SendPulse ↔
Odoo 17 Discuss», версія `17.0.1.15.13`, структура `models/sendpulse_connect.py`,
команди деплою для `odoo_chatwoot_connector`. `fayna_channel_bridge` там не
згаданий жодного разу.

Уся специфікація нового модуля — **103 рядки README** з віхами M0–M3. Немає:
об'єкта й меж, функційних і нефункційних вимог, контрактів вебхуків, моделі
даних, критеріїв приймання, стратегії тестування. Саме тому вимога власника про
мульти-акаунти й OAuth «не реалізована» — вона ніколи не була записана.

### F-21 Відповідність вимогам Odoo 17 — чек-лист

| Вимога Odoo / OCA | Стан |
|---|---|
| `__manifest__.py` повний, коректний | ⚠️ `license: OPL-1` суперечить README і решті репо (LGPL-3); `depends: ["mail","web"]` — `web` зайвий (немає assets) |
| `static/description/icon.png` | ✅ 128×128 PNG |
| `static/description/index.html` | ❌ **немає** — сторінка модуля в Apps порожня |
| i18n `.po` | ❌ **немає жодного**. Гірше: `string=` жорстко українською («Назва», «Канал», «Оператори») — українська стала source language, тому штатний `--i18n-export` дасть українські msgid, а англійська локаль неможлива. Для порівняння: сусідній `omnichannel_bridge` має канонічні uk/pl (921/921) |
| Views для кожної моделі | ❌ лише `channel_backend_views.xml`. `channel.conversation` і `channel.message` мають права доступу, але **жодного списку, форми чи меню** — оператор не має UI |
| `_sql_constraints` / індекси | ⚠️ partial-індекси через raw SQL у `init()` — виправдано (потрібен WHERE), але краще через `odoo.tools.create_index` |
| `_rec_name` / семантика `name` | ⚠️ `channel.message.name = fields.Char(string='Мітка часу')` — поле `name` в Odoo є display name; ніде не заповнюється |
| Структура `migrations/` | ❌ `migrations/migrate_sendpulse_to_channel.py` — не за схемою `migrations/<version>/pre-\|post-migrate.py`, тому Odoo його **ніколи не виконає** автоматично; це просто скрипт |
| Хуки | ❌ див. F-07 — сигнатура Odoo ≤15 |
| Артефакти збірки поза модулем | ⚠️ `Dockerfile.test`, `docker-compose.test.yml` лежать **усередині** каталогу модуля і потрапляють в addons-path |
| `ruff format` | ❌ падає на 3 файлах (`__manifest__.py`, `hooks.py`, `tests/test_security_groups.py`) → pre-commit і CI червоні |
| `ruff check` | ✅ проходить |
| Тести | ⚠️ 3 файли є; **виконання не підтверджено** — доказу проходження немає. CI (`.github/workflows/ci.yml`) запускає **лише lint**, тестового job немає, coverage-гейта немає |

---

## 7. План робіт

Порядок за рішенням власника від 30.08.2026: спершу гаряче, далі стандарт,
ротація секретів — в кінці, коли контур працює на 100%.

### Етап 1 — оживити прод (F-01, F-02, F-04, F-05, F-09)

1. Оператори в Discuss-каналі: успадкування з `backend.user_ids` + fallback на
   групу Officer → **verify:** `SELECT count(*) FROM discuss_channel_member` для
   нового каналу > 0.
2. Перенести `_is_system_message`, `_get_attachment_url` + `SYSTEM_MSG_PATTERNS`
   → **verify:** тест на реальний `message_post` проходить, `channel.message`
   отримує `state='sent'`.
3. Прибрати другий `create` журналу з `_process_incoming_event` → **verify:**
   нове вхідне дає рівно 1 рядок.
4. Матчинг партнера за `provider_user_id` → **verify:** `partner_id` заповнений
   для нової розмови від відомого контакту.
5. `post-migrate`: знести осиротілі `ir.cron` 112 + `ir.act_server` 1357 →
   **verify:** `AttributeError` зникає з `odoo.log` за годину.
6. Бекфіл: додати операторів у 13 наявних каналів, зчистити 19 дублів.

### Етап 2 — безпека (F-03, F-08, F-16, F-19)

HMAC-верифікація всіх вебхуків; Telegram `secret_token` замість токена в URL;
прибрати секрети з логів; звузити `ir.rule` Officer і закрити поле `credentials`;
дедуп без хибних спрацювань на порожньому id.

### Етап 3 — ТЗ + мульти-акаунти + OAuth (F-10, F-11, F-20)

ТЗ за REPO_STANDARD (6 областей) з явними вимогами власника; маршрутизація за
`entry[].id`; перенесення OAuth-шару зі знятого модуля; майстер «Підключити
Facebook / Instagram / WhatsApp» з автопідтягуванням сторінок.

### Етап 4 — стандарт Odoo (F-21)

`index.html` + іконка за гайдом; views і меню для `channel.conversation` /
`channel.message`; i18n (англійські `string=` + uk/pl `.po`); `ruff format`;
тестовий job у CI + coverage-гейт; migrations за схемою Odoo; винести
Docker-файли з каталогу модуля.

### Етап 5 — ротація секретів

Після підтвердженої роботи контуру: нові bot-токени в BotFather, нові Meta App
Secret і Page Access Token, нові webhook-секрети. Потім — верифікація прийому й
відправки в кожному каналі.

---

## Додаток A — доказова база

| Твердження | Команда / джерело | Результат |
|---|---|---|
| Модуль і версія на проді | `SELECT name,state,latest_version FROM ir_module_module` | `fayna_channel_bridge \| installed \| 17.0.1.0.0` |
| Прод не під git | `git log` у каталозі модуля | `fatal: not a git repository` |
| Прод-код = локальний коміт | `md5sum` ↔ `md5 -r`, 17 файлів | збіг усіх, крім незакоміченого маніфесту |
| Канали без учасників | `SELECT count(*) FROM discuss_channel_member` по 13 каналах | `0` у кожному |
| Методи не існують | grep по модулю, всіх аддонах проду, ядру Odoo 17 | 0 визначень |
| Сигнатура хука Odoo 17 | `odoo/modules/loading.py:245-247` у прод-контейнері | `getattr(py_module, post_init)(env)` |
| Дублі вхідних | `GROUP BY service,provider_user_id,date HAVING count(*)>1` | 9 пар, у кожній один `provider_message_id=''` |
| Партнер не прив'язується | `count(partner_id)` для розмов з 26.08 23:30 | `0` із 13 |
| Вихідних немає | `count(*) WHERE direction='outgoing' AND create_date>26.08` | `0` |
| Токен у nginx-логах | `grep -c "bridge/telegram/webhook" /data/logs/proxy-host-6_access.log` | `34` |
| Токен в `odoo.log` | `grep "Telegram webhook set to"` | щогодини, повний токен |
| Шифрування секретів | `grep -rn "encrypt\|Fernet\|cipher"` по модулю | `0` збігів |
| Мертвий cron | `grep -c "cron_bridge_switch_check" odoo.log` | `45` |
| Оператори не призначені | `count(*) FROM channel_backend_res_users_rel` | `0` |
| `ruff format` | `ruff format --check addons/fayna_channel_bridge/` | 3 файли до переформатування |
