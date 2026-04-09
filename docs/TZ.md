# ТЗ — odoo-chatwoot-connector (SendPulse Connector for Odoo 17)

<div style="color:#b00020; border:2px solid #b00020; padding:12px 16px; margin:12px 0; background:#fff8f8; font-weight:600;">

**КРИТИЧНИЙ ІНЦИДЕНТ — 2026-04-09 (червоний рівень)**

Це **критична помилка виконання** та **невиконання мети завдання**: було **явно заборонено** змінювати робочий модуль SendPulse (`sendpulse-odoo` / `odoo_chatwoot_connector`); натомість зміни під помилку Discuss `action.views.map` були внесені саме сюди замість обмеження правок модулем `omnichannel_bridge`. Наслідок — **ризик для стабільного продакшн-контуру**, змушений **повний відкат** гілки `main` до коміту **`6905fa7`** (force-push). Подальші зміни SendPulse — **лише** за окремим погодженим ТЗ.

**Детальний окремий лог (файли, коміти, мотивація, ремедіація):** [`docs/CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md`](CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md).

Короткі дублі: `CHANGELOG.md`, `TECHNICAL_DOCS.md`, `omnichannel-bridge/docs/IMPLEMENTATION_LOG.md`, `omnichannel-bridge/docs/TZ_CHECKLIST.md`, `DevJournal/sessions/2026-04-09-sendpulse-critical-scope-violation.md`.

</div>

> Повний чеклист реалізованих та запланованих функцій.
> ✅ — готово | 🔲 — заплановано | ❌ — скасовано

---

## 1. Базова інфраструктура

| Функція | Статус |
|---------|--------|
| Модель `sendpulse.connect` — розмови | ✅ |
| Модель `sendpulse.message` — повідомлення | ✅ |
| Модель `partner.sendpulse.channel` — канали партнера | ✅ |
| Модель `partner.sendpulse.message` — архів переписки у картці партнера | ✅ |
| Модель `sendpulse.webhook.data` — сирі webhook JSON (7-денна ротація) | ✅ |
| `controllers/main.py` — webhook endpoint `POST /sendpulse/webhook` | ✅ |
| Налаштування: Client ID, Client Secret, Webhook Secret, Webhook URL | ✅ |
| Розмежування доступу: Officer (свої чати) / Administrator (всі) | ✅ |

---

## 2. Підтримувані канали

| Канал | service | Статус |
|-------|---------|--------|
| Telegram | `telegram` | ✅ |
| Instagram | `instagram` | ✅ |
| Facebook | `facebook` | ✅ |
| Messenger | `messenger` | ✅ |
| Viber | `viber` | ✅ |
| WhatsApp | `whatsapp` | ✅ |
| TikTok | `tiktok` | ✅ |
| LiveChat | `livechat` | ✅ |

---

## 3. Прийом повідомлень (Inbound)

| Функція | Статус |
|---------|--------|
| Прийом текстових повідомлень | ✅ |
| Прийом зображень / медіа | ✅ |
| Прийом стікерів | ✅ |
| Прийом файлів | ✅ |
| Завантаження медіа через SendPulse API → Odoo attachment | ✅ |
| Рендеринг `<img>` у Discuss | ✅ |
| Ідентифікація клієнта за email | ✅ |
| Ідентифікація клієнта за телефоном | ✅ |
| Fallback: черга неідентифікованих чатів | ✅ |
| Запобігання дублюванню каналів при повторному контакті | ✅ |

---

## 4. Відправка повідомлень (Outbound)

| Функція | Статус |
|---------|--------|
| Override `mail.channel.message_post()` → SendPulse API | ✅ |
| Текстові відповіді | ✅ |
| Посилання (коректний рендеринг URL) | ✅ |
| Відправка вкладень | 🔲 |

---

## 5. UI / Odoo Discuss

| Функція | Статус |
|---------|--------|
| Розмови в Odoo Discuss | ✅ |
| Сповіщення (дзвіночок) при новому повідомленні | ✅ |
| Stage "new_message" — очищається після відповіді оператора | ✅ |
| `action_close` — закрити розмову | ✅ |
| Список каналів клієнта під полем VAT у картці партнера | ✅ |
| Вкладка "Messaging" в картці партнера | ✅ |

---

## 6. Аналітика та атрибуція

| Функція | Статус |
|---------|--------|
| UTM-атрибуція першого контакту per канал | ✅ |
| Список активних каналів клієнта | ✅ |

---

## 7. Roadmap

| Функція | Статус | Пріоритет |
|---------|--------|-----------|
| Відправка вкладень через Odoo Discuss | 🔲 | Середній |
| Auto-reply шаблони (часті питання) | 🔲 | Середній |
| Інтеграція з `crm.lead` (автоматичний лід при першому контакті) | 🔲 | Низький |
| Статистика по каналах (таблиця) | 🔲 | Низький |
| Підтримка LINE / Signal | 🔲 | Низький |
| Bulk сповіщення (розсилка через SendPulse) | 🔲 | Низький |

---

## Технічний стан (2026-04-03; інцидент 2026-04-09 — див. червоний блок на початку документа)

- **Production:** CampScout (`campscout.eu`)
- **Канали протестовані:** Telegram ✅, Instagram ✅, Facebook ✅, WhatsApp ✅
- **Репо назва:** `odoo-chatwoot-connector` — назва застаріла (насправді SendPulse коннектор)
