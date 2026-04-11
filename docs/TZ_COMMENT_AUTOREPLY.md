# ТЗ: Автовідповідь на коментарі Facebook та Instagram

**Модуль:** `odoo_chatwoot_connector` (SendPulse Odo)
**Версія:** 1.3
**Дата:** 2026-04-11
**Статус:** ✅ Затверджено — готово до реалізації

---

## 1. Бізнес-контекст

### Проблема

Оператор CampScout **не має прямого доступу** до коментарів у Facebook та Instagram через Odoo.
Коли клієнт залишає коментар під рекламним постом (питає ціну, терміни, вік), відбувається таке:

- У Odoo Discuss з'являється нова розмова **без тексту** — незрозуміло що людина написала
- Відповіді на коментарі відсутні — пост виглядає ігнорованим (шкодить репутації та охопленню)
- Клієнт йде без інформації і без початку розмови

### Рішення

Автоматично при надходженні коментаря:
1. **Відповісти публічно під коментарем** — подяка + натяк що надіслали повідомлення у приват
2. **Надіслати приватне повідомлення** через Graph API private_replies — активувати розмову
3. **Повідомити оператора** у Discuss: текст коментаря + що зроблено + очікуємо відповіді

### Логіка Meta (підтверджена)

```
Клієнт пише коментар
    │
    ├─► Публічна відповідь — видна одразу всім
    │       "Написали вам у повідомлення — там детальніше 😊"
    │       ↓ клієнт бачить → цікавиться → перевіряє inbox
    │
    └─► Private Reply → потрапляє у "Запити повідомлень" клієнта
            ↓ клієнт відкриває → відповідає → розмова відкрита
            ↓ після цього: звичайний 24h Messenger window

Якщо клієнт НЕ відповів → ми більше писати не можемо (правило Meta).
Оператор просто очікує. Інших варіантів немає — це нормально.
```

### Цінність

| Ефект | Деталь |
|-------|--------|
| Маркетинг | Публічна відповідь піднімає рейтинг поста в алгоритмі FB/IG |
| Конверсія | Приватне повідомлення активує клієнта до розмови |
| Ефективність | Оператор не витрачає час на моніторинг коментарів вручну |
| Охоплення | Відповідь видна всім — інші люди теж бачать посилання |

---

## 2. Як це працює технічно

### 2.1 Webhook payload для коментаря (реальні дані з БД)

SendPulse надсилає `incoming_message` з вкладеною структурою.
**Ключовий маркер:** `info.message.channel_data.message.item == "comment"`

```json
{
  "service": "messenger",
  "title": "incoming_message",
  "contact": {
    "id": "sendpulse-uuid",
    "name": "Ім'я Клієнта",
    "last_message": null,
    "variables": []
  },
  "info": {
    "message": {
      "channel_data": {
        "message": {
          "item": "comment",
          "verb": "add",
          "comment_id": "966939869621862_2412154672545477",
          "post_id":    "106771868966309_966939869621862",
          "page_id":    "106771868966309",
          "message":    "Дитині 8, яка вартість і терміни?",
          "from": {
            "id":   "9170300446315102",
            "name": "Татьяна Тищенко"
          },
          "post": {
            "permalink_url": "https://www.facebook.com/reel/...",
            "status_type":   "added_video"
          }
        }
      }
    }
  }
}
```

**Відмінності від звичайного повідомлення:**
- `contact.last_message` = **null** (у звичайних — є текст)
- Текст коментаря — у `info.message.channel_data.message.message`
- `item = "comment"` + `verb = "add"` — маркери нового коментаря
- `comment_id` — потрібен для обох API викликів (публічний + приватний)

### 2.2 Чому SendPulse chat API не підходить для нових коментаторів

| Метод | Для кого | Результат |
|-------|----------|-----------|
| `/messenger/contacts/send` тип RESPONSE | Лише активні підписники бота | 400 `not_active` для нових |
| **Graph API `/{comment_id}/private_replies`** | **Будь-який коментатор** | ✅ Доходить без opt-in |

**Рішення:** Використовувати **Facebook Graph API напряму** з Page Access Token.

---

## 3. Функціональні вимоги

### F1 — Розпізнавання коментаря ✅ Must

У методі `_process_incoming_event`:

```python
channel_data_msg = (
    data.get('info', {})
    .get('message', {})
    .get('channel_data', {})
    .get('message', {})
)
is_comment = (
    isinstance(channel_data_msg, dict)
    and channel_data_msg.get('item') == 'comment'
    and channel_data_msg.get('verb') == 'add'
)
if is_comment:
    return self._process_comment_event(...)
```

---

### F2 — Зберігання даних коментаря ✅ Must

Нові поля у `sendpulse.connect`:

```python
sp_is_comment          = fields.Boolean('Ініційовано з коментаря', default=False)
sp_comment_id          = fields.Char('Facebook/Instagram Comment ID')
sp_comment_text        = fields.Char('Текст коментаря', size=500)
sp_post_id             = fields.Char('Post ID')
sp_post_url            = fields.Char('URL допису')
sp_replied_private     = fields.Boolean('Приватна відповідь надіслана', default=False)
sp_replied_public      = fields.Boolean('Публічна відповідь надіслана', default=False)
```

Відображення у формі розмови — секція "Коментар" (видима тільки якщо `sp_is_comment = True`).

---

### F3 — Публічна відповідь під коментарем ✅ Must

**Facebook:**
```http
POST https://graph.facebook.com/v19.0/{comment_id}/comments
Content-Type: application/json

{
  "message": "{текст_публічної_відповіді}",
  "access_token": "{page_access_token}"
}
```

**Instagram:**
```http
POST https://graph.facebook.com/v19.0/{comment_id}/replies
Content-Type: application/json

{
  "message": "{текст_публічної_відповіді}",
  "access_token": "{page_access_token}"
}
```

---

### F4 — Приватне повідомлення ✅ Must

**Facebook Messenger і Instagram Direct — однаковий endpoint:**
```http
POST https://graph.facebook.com/v19.0/{comment_id}/private_replies
Content-Type: application/json

{
  "message": "{текст_приватного_повідомлення}",
  "access_token": "{page_access_token}"
}
```

Умови Meta:
- Дозволено **без попередньої взаємодії** клієнта з ботом
- Вікно: **7 днів** після коментаря
- Одне повідомлення на коментар
- Повідомлення потрапляє у "Запити повідомлень" — клієнт бачить тільки якщо перейде туди

---

### F5 — Дедуплікація ✅ Must

**Правило (маркетингова логіка):**

| Дія | Правило | Обґрунтування |
|-----|---------|---------------|
| Публічна відповідь | **Завжди** — на кожен коментар | Видна ВСІЙ аудиторії поста, підвищує охоплення алгоритму FB/IG |
| Приватне повідомлення | **Тільки перше** — по одному на контакт | Щоб не надсилати однаковий текст двічі одному клієнту |

**Захист від дублювання одного і того ж коментаря** (SendPulse може надіслати двічі):
```python
existing = self.search([('sp_comment_id', '=', comment_id)], limit=1)
if existing:
    return existing  # той самий comment_id — нічого не робимо
```

**Визначення чи надсилати private_reply:**
```python
already_private = self.search([
    ('sendpulse_contact_id', '=', contact_id),
    ('sp_replied_private', '=', True),
], limit=1)
send_private = not bool(already_private)
```

**Публічна відповідь — ротація текстів** (щоб не виглядало як бот):
Система по черзі використовує один з 5 варіантів публічної відповіді.
Посилання на лендінг і ТГ-канал підставляються з налаштувань (`{landing_url}`, `{tg_url}`).

- Варіант 1: "Дякуємо за коментар! 🏕️ Написали вам детальніше у приватні — перевірте вхідні 😊 Або одразу: {landing_url}"
- Варіант 2: "Дякуємо! 🌟 Всі деталі надіслали в особисті. Також можна одразу глянути програму: {landing_url}"
- Варіант 3: "Радіємо вашій зацікавленості! ✨ Написали в приват — там детальна відповідь. Підписуйтесь на наш ТГ-канал і отримайте -5% на табір: {tg_url} 🎁"
- Варіант 4: "Привіт! Відповіли вам у повідомленнях 📩 Актуальні табори 2026 та знижка -5% за підписку: {tg_url}"
- Варіант 5: "Дякуємо за інтерес! 🏕️ Детальніше написали у приватних. Все про табори 2026: {landing_url}"

Ротація по `(count of existing sp_is_comment records) % 5`.

> **Маркетингова логіка:** посилання на лендінг і ТГ-канал видимі ВСІЙ аудиторії поста —
> інші відвідувачі можуть одразу перейти без написання коментаря. Знижка -5% стимулює підписку і фіксує теплу аудиторію.

---

### F6 — Сповіщення оператора у Discuss ✅ Must

Системна нотатка від OdooBot у Discuss-каналі розмови:

```
💬 Новий коментар під постом [Facebook / Instagram]

👤 Клієнт: Татьяна Тищенко
📝 Коментар: "Дитині 8, яка вартість і терміни?"
🔗 Допис: https://www.facebook.com/reel/...

✅ Публічна відповідь опублікована під коментарем
✅ Приватне повідомлення надіслано у Messenger
⏳ Очікуємо відповіді від клієнта — поки клієнт не відповів, писати йому не можна (правило Meta)
```

Якщо щось не вдалось:
```
❌ Приватне повідомлення не надіслано: минуло більше 7 днів з моменту коментаря
⚠️ Публічна відповідь: помилка API — {деталь}
```

---

### F7 — Налаштування у Settings ✅ Must

Нова секція **"SendPulse — Відповіді на коментарі"** у Налаштування → Обговорення:

| Поле | Тип | Параметр | Дефолт |
|------|-----|---------|--------|
| Автовідповідь на коментарі | Boolean | `sp_comment_autoreply_enabled` | True |
| Публічна відповідь | Boolean | `sp_comment_public_enabled` | True |
| Приватне повідомлення | Boolean | `sp_comment_private_enabled` | True |
| Facebook Page Access Token | Char (password) | `fb_page_access_token` | — |
| URL лендінгу (у публічних відповідях) | Char | `sp_comment_landing_url` | https://lato2026.campscout.eu |
| URL ТГ-каналу (у публічних відповідях) | Char | `sp_comment_tg_url` | https://t.me/campscouting |
| URL YouTube-плейлисту (у приватних) | Char | `sp_comment_yt_url` | https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV |
| Текст приватного повідомлення | Text | `sp_comment_private_text` | §4.2 |
| Текст публічної відповіді (повторний) | Text | `sp_comment_public_repeat_text` | §4.3 |

> **Примітка:** Тексти 5 ротаційних публічних відповідей — вшиті в код як константи з підстановкою `{landing_url}` / `{tg_url}` з параметрів. Окреме поле для кожного варіанта не потрібне — редагування через Deploy.

---

## 4. Тексти автовідповідей

### 4.1 Публічна відповідь — 5 ротаційних варіантів

`{landing_url}` і `{tg_url}` підставляються з `ir.config_parameter`. Якщо параметр порожній — підрядок з посиланням пропускається.

**Варіант 1** (акцент: лендінг):
> Дякуємо за коментар! 🏕️ Написали вам детальніше у приватні — перевірте вхідні 😊 Або одразу: {landing_url}

**Варіант 2** (акцент: лендінг + деталі в особисті):
> Дякуємо! 🌟 Всі деталі надіслали в особисті. Також можна одразу глянути програму: {landing_url}

**Варіант 3** (акцент: ТГ + знижка -5%):
> Радіємо вашій зацікавленості! ✨ Написали в приват — там детальна відповідь. Підписуйтесь на наш ТГ-канал і отримайте -5% на табір: {tg_url} 🎁

**Варіант 4** (акцент: ТГ + знижка -5%, стисло):
> Привіт! Відповіли вам у повідомленнях 📩 Актуальні табори 2026 та знижка -5% за підписку: {tg_url}

**Варіант 5** (нейтральний, акцент: лендінг):
> Дякуємо за інтерес! 🏕️ Детальніше написали у приватних. Все про табори 2026: {landing_url}

*(Стисло. Мета: змусити клієнта відкрити inbox + залишити лінк іншим відвідувачам.)*

### 4.2 Приватне повідомлення (Messenger / Instagram Direct) — варіанти

**Шаблон використовує `{landing_url}` і `{yt_url}` — підставляються з `ir.config_parameter`.**

**Дефолтні значення:**
- `{landing_url}` → `https://lato2026.campscout.eu`
- `{yt_url}` → `https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV`

**Варіант A — з акцентом на відповідь на питання (дефолт):**
> Вітаємо! 🏕️ Дякуємо за ваш коментар під нашим постом.
>
> Підготували для вас відповіді на найпоширеніші запитання — безпека, програма, харчування, вартість, терміни:
> 🎬 {yt_url}
>
> Вся актуальна інформація про табори 2026 також тут:
> 🌐 {landing_url}
>
> Якщо залишились питання — пишіть тут, відповімо особисто! 😊

**Варіант B — коротший, з акцентом на розмову:**
> Привіт! 👋 Побачили ваш коментар і одразу написали 😊
>
> Усі деталі про табори CampScout 2026 — на сайті: {landing_url}
>
> Або перегляньте короткі відео з відповідями для батьків: {yt_url}
>
> Будь-яке питання — просто відповідайте тут, допоможемо! 🏕️

**Варіант C — найстисліший:**
> Дякуємо за інтерес до CampScout! 🏕️
> Деталі про табори 2026: {landing_url}
> Питання? Пишіть — відповімо особисто 😊

*Дефолтний варіант у Settings: **A**. Можна змінити через Налаштування без змін коду.*

### 4.3 Публічна відповідь — повторний коментар (клієнт вже отримував приватне)

> Раді бачити вас знову! 😊 Наш менеджер вже напише вам у повідомленнях — слідкуйте за вхідними 🏕️

---

## 5. Де взяти Facebook Page Access Token

### Крок 1 — Увійти у Facebook Developer Portal
Перейти: https://developers.facebook.com/apps

### Крок 2 — Вибрати або створити App
- Якщо App для CampScout вже є (через SendPulse) — вибрати його
- Якщо ні — створити новий: тип **Business**

### Крок 3 — Graph API Explorer
Перейти: https://developers.facebook.com/tools/explorer/
- Вибрати свій **App** у правому верхньому куті
- Вибрати **Page** (CampScout) замість User
- Натиснути **Generate Access Token**
- Підтвердити permissions (список нижче)

### Необхідні permissions
```
pages_manage_posts
pages_read_engagement
pages_manage_engagement     ← для публікації відповіді під коментарем
pages_messaging             ← для private_replies
instagram_basic             ← для Instagram
instagram_manage_comments   ← для Instagram comment replies
instagram_manage_messages   ← для Instagram private_replies
```

### Крок 4 — Довгостроковий токен (важливо!)
Стандартний токен живе **1 годину**. Для продакшн потрібен **довгостроковий (60 днів)**:

```bash
curl -X GET "https://graph.facebook.com/v19.0/oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id={app_id}
  &client_secret={app_secret}
  &fb_exchange_token={short_lived_token}"
```

### Крок 5 — Page Token з довгострокового User Token
```bash
curl -X GET "https://graph.facebook.com/v19.0/me/accounts
  ?access_token={long_lived_user_token}"
```
→ У відповіді знайти об'єкт з `name: "CampScout"` → взяти його `access_token`.
Це буде **безстроковий Page Token** (не потребує оновлення поки App активний).

### Де вставити в Odoo
`Налаштування → Обговорення → SendPulse — Відповіді на коментарі → Facebook Page Access Token`

---

## 6. Структура коду

### 6.1 Нові файли / зміни

| Файл | Зміна |
|------|-------|
| `models/sendpulse_connect.py` | Нові поля + `_process_comment_event`, `_send_comment_public_reply`, `_send_comment_private_reply`, `_notify_operator_comment` |
| `models/res_config_settings.py` | Нові поля: token, тексти, toggles |
| `views/sendpulse_connect_views.xml` | Секція "Коментар" у формі (visible if `sp_is_comment`) |
| `views/res_config_settings_views.xml` | Секція "SendPulse — Відповіді на коментарі" |
| `CHANGELOG.md` | Запис v17.0.3.0.0 |

### 6.2 Нові методи

```python
@api.model
def _process_comment_event(self, data, contact, bot, service,
                            comment_id, comment_text, post_id, post_url):
    """
    1. Дедуплікація по comment_id
    2. Знайти/створити sendpulse.connect (sp_is_comment=True)
    3. _send_comment_public_reply() — публічна відповідь
    4. _send_comment_private_reply() — тільки якщо перший коментар
    5. _notify_operator_comment() — нотатка у Discuss
    6. sp_replied_public / sp_replied_private = True
    """

def _send_comment_public_reply(self, comment_id, service, text):
    """
    Facebook: POST /v19.0/{comment_id}/comments
    Instagram: POST /v19.0/{comment_id}/replies
    Повертає (success: bool, error: str|None)
    """

def _send_comment_private_reply(self, comment_id, text):
    """
    POST /v19.0/{comment_id}/private_replies
    Працює для Facebook і Instagram.
    Повертає (success: bool, error: str|None)
    """

def _get_fb_page_token(self):
    """ir.config_parameter → odoo_chatwoot_connector.fb_page_access_token"""

def _notify_operator_comment(self, comment_text, post_url,
                              sent_private, sent_public,
                              private_error, public_error):
    """Системна нотатка OdooBot у Discuss-каналі розмови."""
```

---

## 7. Flow діаграма

```
SendPulse webhook → POST /sendpulse/webhook
    │
    ▼
handle_webhook() → event=incoming_message, item=comment?
    │                           │
    │ ТАК                       │ НІ
    ▼                           ▼
_process_comment_event()   _process_incoming_event() (існуючий)
    │
    ├─ comment_id вже є в БД?
    │   ТАК → skip (дедуплікація)
    │   НІ  → продовжити
    │
    ├─ Знайти/створити sendpulse.connect
    │   sp_is_comment=True, sp_comment_text=..., sp_comment_id=...
    │
    ├─ Публічна відповідь (якщо увімкнена)
    │   └─ Graph API POST /{comment_id}/comments (FB) або /replies (IG)
    │       ✅ sp_replied_public=True
    │       ❌ логуємо помилку
    │
    ├─ Приватне повідомлення (якщо перший коментар + увімкнено)
    │   └─ Graph API POST /{comment_id}/private_replies
    │       ✅ sp_replied_private=True
    │       ❌ логуємо помилку
    │
    └─ Нотатка оператору у Discuss
        "💬 Коментар від X: '...' | ✅ публічна | ✅ приватна | ⏳ очікуємо"
```

---

## 8. Критерії прийняття (Definition of Done)

- [ ] Коментар під постом FB → публічна відповідь з'являється під тим самим коментарем (видно всім)
- [ ] Коментар → приватне повідомлення приходить у Messenger клієнту (навіть якщо не підписник бота)
- [ ] Коментар Instagram → ті самі дії через Instagram API
- [ ] У Odoo Discuss: нотатка з текстом коментаря + URL поста + що зроблено
- [ ] Повторний коментар від того самого клієнта → тільки публічна, без повторного приватного
- [ ] Помилка Graph API (токен прострочений, >7 днів) → чітке повідомлення оператору в Discuss
- [ ] Тексти відповідей редагуються через Налаштування без змін коду
- [ ] Page Access Token зберігається у `ir.config_parameter` (не у коді, не у репо)
- [ ] CHANGELOG.md оновлено → версія 17.0.3.0.0
- [ ] Коміт з описом згідно `repo-deploy-server-gate.mdc`

---

## 9. Відкриті питання — ЗАКРИТІ

| № | Питання | Відповідь |
|---|---------|-----------|
| 1 | API: SendPulse чи Graph API напряму? | **Graph API напряму** з Page Token |
| 2 | Де взяти Page Token? | **§5 цього документу** — покрокова інструкція |
| 3 | Instagram для v1.0? | **Так**, та сама логіка, той самий endpoint |
| 4 | Кілька коментарів від одного клієнта? | **Тільки перший** отримує приватне. Публічна — завжди. Тексти §4.3 |
| 5 | Кнопка ручної відповіді? | **Не потрібна в v1.0.** Публічна відповідь каже що менеджер пише у приват |
| 6 | Логіка Meta щодо першого повідомлення? | **Підтверджено:** private_replies не потребує opt-in. Клієнт бачить у "Запитах". Якщо не відповів — ми нічого не можемо. Оператор чекає. |
