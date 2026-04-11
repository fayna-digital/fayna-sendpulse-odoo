# ТЗ: Автовідповідь на коментарі Facebook та Instagram

**Модуль:** `odoo_chatwoot_connector` (SendPulse Odo)
**Версія:** 1.0
**Дата:** 2026-04-11
**Статус:** ✅ Затверджено — очікує реалізації

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
1. **Публічно відповісти під коментарем** — подяка + посилання на лендінг або YouTube
2. **Надіслати приватне повідомлення** у Messenger / Instagram Direct — активувати розмову
3. **Повідомити оператора** у Discuss що розмову ініційовано, показати текст коментаря

### Цінність

| Ефект | Деталь |
|-------|--------|
| Маркетинг | Публічна відповідь піднімає рейтинг поста в алгоритмі FB/IG |
| Конверсія | Приватне повідомлення активує клієнта до розмови |
| Ефективність | Оператор не витрачає час на моніторинг коментарів вручну |
| Охоплення | Відповідь видно всім — інші люди теж бачать посилання |

---

## 2. Як це працює технічно

### 2.1 Webhook payload для коментаря (факт з бази даних)

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
- `comment_id` — потрібен для публічної відповіді через Graph API
- `post_id` — ідентифікатор допису де залишили коментар

### 2.2 Архітектурна проблема: чому `not_active`

Поточний код використовує `/messenger/contacts/send` з `type: "RESPONSE"`.
Цей тип вимагає щоб клієнт **раніше взаємодіяв з ботом у Messenger**.
Для нових коментаторів → `400 contact.errors.not_active`.

**Правильний підхід для коментарів:**
Facebook дозволяє **Private Reply** без попередньої взаємодії з ботом,
але через **Facebook Graph API** напряму, а не через SendPulse chat endpoint.

| Метод | Для кого працює | Вимога |
|-------|----------------|--------|
| `/messenger/contacts/send` (тип RESPONSE) | Лише активні підписники бота | Попередня взаємодія з ботом |
| Facebook Graph API `/{comment_id}/private_replies` | **Будь-який коментатор** | Page Access Token + 7 днів з моменту коментаря |
| SendPulse `/facebook/comments/reply` | Потребує уточнення у SP | Можливо достатньо SP OAuth |

**Висновок для реалізації:** Приватна відповідь на коментар повинна йти через
**Facebook Graph API** `/{comment_id}/private_replies`, а не через SendPulse chat API.

---

## 3. Функціональні вимоги

### F1 — Розпізнавання коментаря ✅ Must

У методі `_process_incoming_event` (controllers/main.py → sendpulse_connect.py):

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
```

Якщо `is_comment` → не обробляти як звичайне повідомлення, а викликати `_process_comment_event()`.

---

### F2 — Зберігання даних коментаря ✅ Must

Нові поля у моделі `sendpulse.connect`:

```python
sp_is_comment          = fields.Boolean('Ініційовано з коментаря', default=False)
sp_comment_id          = fields.Char('Facebook Comment ID')
sp_comment_text        = fields.Char('Текст коментаря', size=500)
sp_post_id             = fields.Char('Facebook Post ID')
sp_post_url            = fields.Char('URL допису')
sp_replied_private     = fields.Boolean('Приватна відповідь надіслана', default=False)
sp_replied_public      = fields.Boolean('Публічна відповідь надіслана', default=False)
```

Відображення у формі розмови — нова секція "Коментар" (видима тільки якщо `sp_is_comment = True`).

---

### F3 — Публічна відповідь під коментарем ✅ Must (Facebook), Should (Instagram)

**Facebook — через Facebook Graph API:**

```http
POST https://graph.facebook.com/v19.0/{comment_id}/comments
Content-Type: application/json

{
  "message": "{текст публічної відповіді}",
  "access_token": "{page_access_token}"
}
```

**Instagram — через Instagram Graph API:**

```http
POST https://graph.facebook.com/v19.0/{comment_id}/replies
Content-Type: application/json

{
  "message": "{текст публічної відповіді}",
  "access_token": "{page_access_token}"
}
```

Новий параметр у Settings: `facebook_page_access_token` (зберігається у `ir.config_parameter`).

---

### F4 — Приватне повідомлення у Messenger/Instagram Direct ✅ Must

**Facebook Messenger — через Graph API Private Reply:**

```http
POST https://graph.facebook.com/v19.0/{comment_id}/private_replies
Content-Type: application/json

{
  "message": "{текст приватного повідомлення}",
  "access_token": "{page_access_token}"
}
```

Цей метод працює **без попередньої взаємодії** клієнта з ботом (на відміну від SendPulse chat API).
Дозволено протягом **7 днів** після коментаря.

**Instagram Direct** — аналогічно через `/{comment_id}/private_replies` Instagram API.

> ⚠️ **Важливо:** Після того як клієнт відповів у приватному — подальше листування
> веде вже через SendPulse webhook (incoming_message) як звичайна розмова.

---

### F5 — Сповіщення оператора у Discuss ✅ Must

Системна нотатка (від OdooBot) у Discuss-каналі розмови одразу після дій:

```
💬 Новий коментар під постом [Facebook / Instagram]

👤 Клієнт: Татьяна Тищенко
📝 Коментар: "Дитині 8, яка вартість і терміни?"
🔗 Допис: https://www.facebook.com/reel/...

✅ Публічна відповідь надіслана під коментарем
✅ Приватне повідомлення надіслано у Messenger
⏳ Очікуємо відповіді від клієнта
```

Якщо приватна або публічна відповідь не вдалась — показувати причину:
```
❌ Приватне повідомлення не доставлено: вікно відповіді закрите (>7 днів)
```

---

### F6 — Налаштування у Settings ✅ Must

Нова секція "SendPulse — Коментарі" у `Налаштування → Обговорення`:

| Поле | Тип | Дефолт | Опис |
|------|-----|--------|------|
| Автовідповідь на коментарі | Boolean | True | Вмикає/вимикає всю фічу |
| Публічна відповідь | Boolean | True | Відповідати публічно під коментарем |
| Приватне повідомлення | Boolean | True | Надсилати приватний Messenger/DM |
| Facebook Page Access Token | Char (password) | — | Токен сторінки FB для Graph API |
| Текст публічної відповіді (варіант А) | Text | (нижче) | З посиланням на лендінг |
| Текст публічної відповіді (варіант Б) | Text | (нижче) | З посиланням на YouTube |
| Активний варіант публічної відповіді | Selection (А/Б) | А | Який текст використовувати |
| Текст приватного повідомлення | Text | (нижче) | Шаблон для Messenger/DM |

---

### F7 — Дедуплікація ✅ Must

Не надсилати повторно якщо:
- `sp_replied_private = True` — вже надіслали приватне
- `sp_replied_public = True` — вже відповіли публічно
- Той самий `comment_id` вже є в базі

Перевірка на початку `_process_comment_event()`:
```python
existing = self.search([('sp_comment_id', '=', comment_id)], limit=1)
if existing and existing.sp_replied_private and existing.sp_replied_public:
    return existing  # нічого не робимо
```

---

## 4. Тексти автовідповідей

### 4.1 Публічна відповідь — Варіант А (лендінг)

> Дякуємо за коментар! 🏕️ Усі деталі про табори, вартість та терміни — на нашому сайті:
> https://lato2026.campscout.eu
> Якщо виникнуть питання — пишіть у повідомлення, відповімо особисто 😊

### 4.2 Публічна відповідь — Варіант Б (YouTube)

> Дякуємо за коментар! 🎬 Відповіді на головні питання батьків (безпека, програма, харчування, побут):
> https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV
> Написали вам у приватні повідомлення — там зручно поговорити детальніше 😊

### 4.3 Приватне повідомлення (Messenger / Instagram Direct)

> Вітаємо! 🏕️ Дякуємо за ваш коментар під нашим постом.
>
> Ми підготували відповіді на найпоширеніші запитання батьків — безпека, програма, харчування, доїзд, вартість і терміни:
> 🎬 https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV
>
> Також вся актуальна інформація про табори 2026 на сайті:
> 🌐 https://lato2026.campscout.eu
>
> Якщо залишились питання — пишіть тут, відповімо особисто! 😊

---

## 5. Структура коду

### 5.1 Нові файли / зміни

| Файл | Зміна |
|------|-------|
| `models/sendpulse_connect.py` | Нові поля + методи `_process_comment_event`, `_send_comment_public_reply`, `_send_comment_private_reply` |
| `models/res_config_settings.py` | Нові поля налаштувань |
| `views/sendpulse_connect_views.xml` | Нова секція "Коментар" у формі розмови |
| `views/res_config_settings_views.xml` | Нова секція "SendPulse — Коментарі" |
| `security/ir.model.access.csv` | Без змін (нові поля на існуючій моделі) |

### 5.2 Нові методи у `sendpulse_connect.py`

```python
@api.model
def _process_comment_event(self, data, contact, bot, service,
                            comment_id, comment_text, post_id, post_url):
    """
    Обробляє вхідний коментар під постом FB/IG.
    1. Знайти або створити sendpulse.connect (без discuss.channel поки)
    2. Зберегти comment_id, comment_text, post_id
    3. Публічна відповідь (якщо увімкнена)
    4. Приватне повідомлення (якщо увімкнена)
    5. Сповістити оператора у Discuss
    """

def _send_comment_public_reply(self, comment_id, service):
    """
    POST /{comment_id}/comments (Facebook)
    POST /{comment_id}/replies  (Instagram)
    через Facebook Graph API v19.0 з Page Access Token.
    Повертає True/False.
    """

def _send_comment_private_reply(self, comment_id, service):
    """
    POST /{comment_id}/private_replies через Facebook Graph API.
    Не потребує попередньої взаємодії з ботом (на відміну від SendPulse chat API).
    Дозволено протягом 7 днів після коментаря.
    Повертає True/False.
    """

def _get_facebook_page_token(self):
    """
    Читає Page Access Token з ir.config_parameter.
    """

def _notify_operator_comment(self, comment_text, post_url,
                              sent_private, sent_public,
                              private_error=None, public_error=None):
    """
    Системна нотатка у Discuss-каналі розмови з підсумком дій.
    """
```

---

## 6. Flow діаграма

```
SendPulse webhook
    │
    ▼
controllers/main.py: handle_webhook()
    │
    ├─ event_type = incoming_message
    │   ├─ item = "comment"? ──► _process_comment_event()
    │   │                              │
    │   │                              ├─ Дедуплікація по comment_id
    │   │                              │
    │   │                              ├─ Публічна відповідь
    │   │                              │   └─ Graph API POST /{comment_id}/comments
    │   │                              │
    │   │                              ├─ Приватне повідомлення
    │   │                              │   └─ Graph API POST /{comment_id}/private_replies
    │   │                              │
    │   │                              ├─ Створити sendpulse.connect (stage=new)
    │   │                              │   sp_is_comment=True
    │   │                              │   sp_comment_text="текст коментаря"
    │   │                              │
    │   │                              └─ Нотатка оператору у Discuss
    │   │
    │   └─ item ≠ "comment" ──► _process_incoming_event() (існуючий flow)
    │
    └─ event_type = outbound/unsubscribe ──► існуючі handlers
```

---

## 7. Що НЕ входить у scope v1.0

- Аналіз тексту коментаря (NLP) для вибору відповідного шаблону відповіді
- Автоматичне закриття розмови якщо клієнт не відповів протягом N днів
- Статистика по коментарях у Odoo (окремий звіт)
- Підтримка коментарів у Instagram Stories (окремий API flow)
- A/B тестування текстів відповідей

---

## 8. Передумови для реалізації

До початку кодування потрібно:

1. ✅ Знайти Facebook Page Access Token для сторінки CampScout
   - Facebook Business Manager → Налаштування → Розширений доступ → Page Token
   - Або через Facebook Developer App (Graph API Explorer)
   - Потрібні permissions: `pages_manage_posts`, `pages_read_engagement`,
     `pages_manage_engagement`, `instagram_basic`, `instagram_manage_comments`

2. ✅ Перевірити чи SendPulse має окремий endpoint для reply-to-comment
   - Якщо є — можна не використовувати Graph API напряму
   - Перевірити у кабінеті SendPulse → API → документація

3. ✅ Тест: надіслати `POST /{comment_id}/private_replies` вручну через Graph API Explorer
   - Переконатись що `not_active` помилки не виникають (Graph API обходить це обмеження)

---

## 9. Критерії прийняття (Definition of Done)

- [ ] Коментар під постом FB/IG → публічна відповідь з'являється під тим самим коментарем
- [ ] Коментар → приватне повідомлення приходить у Messenger/IG Direct клієнту
- [ ] У Odoo Discuss з'являється розмова з нотаткою: текст коментаря + що зроблено
- [ ] Повторний коментар від того самого клієнта → не дублює відповіді
- [ ] Якщо приватне не вдалось (>7 днів) → оператор бачить причину в Discuss
- [ ] Тексти відповідей редагуються через Налаштування Odoo без змін коду
- [ ] Фіча вимикається повністю одним перемикачем у Налаштуваннях
- [ ] Всі зміни покриті комітом з описом + оновлено CHANGELOG.md

---

## 10. Відкриті питання (для уточнення перед кодом)

| № | Питання | Від кого | Статус |
|---|---------|----------|--------|
| 1 | Чи є Facebook Page Access Token для сторінки CampScout? | Замовник | ⏳ |
| 2 | Публічна відповідь — Варіант А (сайт) чи Б (YouTube) як дефолт? | Замовник | ⏳ |
| 3 | Instagram Direct — пріоритет для v1.0 чи відкласти? | Замовник | ⏳ |
| 4 | Що робити якщо той самий клієнт напише 2+ коментарі під різними постами? | Замовник | ⏳ |
| 5 | Чи потрібна кнопка "Відповісти на коментар вручну" у формі розмови? | Замовник | ⏳ |
