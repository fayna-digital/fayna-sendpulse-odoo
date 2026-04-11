# 💬 SendPulse Omnichannel Connector for Odoo 17

![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20Community-purple)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![SendPulse](https://img.shields.io/badge/SendPulse-Webhook%20API-red)
![License](https://img.shields.io/badge/License-LGPL--3.0-green.svg)
![Status](https://img.shields.io/badge/Status-Production-brightgreen)

**Developed by [Fayna Digital](https://fayna.agency) — Author: Volodymyr Shevchenko**

---

Модуль інтеграції **SendPulse** чат-ботів з **Odoo 17**.

**Критичні інциденти AI (межі модуля):** [docs/CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md](docs/CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md) (розділ 7 — доповнення **2026-04-11**). Сесійний зведений журнал: `DevJournal/sessions/LOG.md`.

Всі розмови з месенджерів (Telegram, Instagram, Facebook, Viber, WhatsApp та ін.) автоматично потрапляють в Odoo Discuss. Оператори відповідають клієнтам прямо з Odoo — повідомлення летять назад через SendPulse API.

---

## Можливості

- Отримання повідомлень через Webhook у реальному часі
- Автоматична ідентифікація клієнтів за email або телефоном → прив'язка до картки партнера
- Черга нових та неідентифікованих чатів для операторів
- Повна двостороння переписка у Odoo Discuss (дзвіночок сповіщень)
- Відповідь клієнту прямо з Odoo → повідомлення надсилається через SendPulse API
- Підтримка вкладень (фото, файли)
- Зберігання всієї історії переписки у вкладці **Messaging** картки партнера
- Список каналів клієнта (Telegram, Instagram тощо) під полем VAT у картці партнера
- UTM-атрибуція першого контакту по кожному каналу
- Розмежування доступу: Officer (свої чати) / Administrator (всі чати)

## Підтримувані канали

| Канал | service |
|-------|---------|
| Telegram | `telegram` |
| Instagram | `instagram` |
| Facebook | `facebook` |
| Messenger | `messenger` |
| Viber | `viber` |
| WhatsApp | `whatsapp` |
| TikTok | `tiktok` |
| LiveChat | `livechat` |

---

## Встановлення

### Вимоги

- Odoo 17.0 (Community або Enterprise)
- Python пакет `requests`
- Odoo модулі: `mail`, `contacts`, `crm`, `web`

### Кроки

```bash
# 1. Клонувати в папку custom-addons
cd /your/odoo/custom-addons
git clone https://github.com/VladSh77/odoo-chatwoot-connector odoo_chatwoot_connector

# 2. Встановити модуль
odoo -i odoo_chatwoot_connector -d YOUR_DB --stop-after-init
```

Або через інтерфейс: **Settings → Apps → пошук "SendPulse Odo" → Install**

---

## Налаштування

### 1. Отримай API ключі у SendPulse

`Profile → Settings → API → API Credentials` → скопіюй **Client ID** та **Client Secret**

### 2. Заповни в Odoo

`SendPulse → Налаштування`:
- **SendPulse Client ID**
- **SendPulse Client Secret**
- **Webhook Secret Token** — довільний рядок
- **Webhook URL** — генерується автоматично (напр. `https://your-domain.com/sendpulse/webhook`)

### 3. Налаштуй Webhook у SendPulse

`Chatbots → Бот → Settings → Webhooks → Add Webhook`

URL: скопіюй з поля Webhook URL в Odoo

Відмічені події:
- ✅ Підписка на бота
- ✅ Вхідне повідомлення
- ✅ Відкриття чату
- ✅ Відписка від бота

### 4. Надай доступ операторам

`Settings → Users → користувач → SendPulse Odo → Officer або Administrator`

---

## Архітектура

```
SendPulse (месенджери)
       │  Webhook POST /sendpulse/webhook
       ▼
controllers/main.py          ← приймає JSON, зберігає сирі дані
       │
       ▼
models/sendpulse_connect.py  ← бізнес-логіка: ідентифікація, розмови, API
       │
       ├── sendpulse.connect          (розмови)
       ├── sendpulse.message          (повідомлення розмови)
       ├── partner.sendpulse.channel  (канали партнера)
       ├── partner.sendpulse.message  (Messaging вкладка)
       └── sendpulse.webhook.data     (сирі webhook дані)
       │
       ▼
models/mail_channel.py       ← override message_post → відповідь назад у API
       │
       ▼
SendPulse API → клієнт отримує відповідь у месенджері
```

## Моделі даних

| Модель | Опис |
|--------|------|
| `sendpulse.connect` | Розмова (одна на клієнта + канал) |
| `sendpulse.message` | Повідомлення розмови |
| `partner.sendpulse.channel` | Соціальні канали партнера |
| `partner.sendpulse.message` | Архів переписки у картці партнера |
| `sendpulse.webhook.data` | Сирі webhook JSON (очищаються кожні 7 днів) |

---

## Документація

Повна технічна документація: [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md)

---

## Ліцензія

[LGPL-3.0](LICENSE)

---

*Розроблено для [CampScout](https://campscout.eu) — платформи організації дитячих таборів.*
