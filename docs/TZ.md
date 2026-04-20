# TZ — Fayna SendPulse Odo

**Module version:** `17.0.3.7.1` · **Last updated:** 2026-04-20

Umbrella технічне завдання. Поточний стан модуля + roadmap + sub-TZs за окремими фічами.

---

## Зміст

1. [Поточний стан (v17.0.3.7.1)](#1-поточний-стан-v170371)
2. [Roadmap](#2-roadmap)
3. [Sub-TZs](#3-sub-tzs)
4. [Критичні правила](#4-критичні-правила)
5. [Архівні TZ (історія)](#5-архівні-tz-історія)
6. [Постмортеми](#6-постмортеми)

---

## 1. Поточний стан (v17.0.3.7.1)

### 1.1 Функціонал (готово і деплойнуто)

**Core (17.0.x):**
- ✅ Webhook прийом (Telegram / IG / FB / Messenger / Viber / WhatsApp / LiveChat / TikTok)
- ✅ Двостороннє спілкування через Odoo Discuss
- ✅ Автоматична ідентифікація партнера (email/phone/bot-vars)
- ✅ Queue-based pickup (stage `new` → operator кликає → `in_progress`)
- ✅ Auto-greeting нового контакту (2 повідомлення)
- ✅ UTM-атрибуція першого контакту
- ✅ Архів переписки у Messaging вкладці картки партнера
- ✅ Cron відновлення втрачених webhooks (`cron_pull_missing_contacts`)
- ✅ Public User контамінація захищена (fixed у v17.0.2.x)

**Comment autoreply (17.0.3.x):**
- ✅ FB/IG comment webhook detection (item='comment'+verb='add' + IG feed)
- ✅ Public reply через Graph v25.0 з 5-шаблонною ротацією per-post
- ✅ Private reply (FB private_replies + IG /{ig_user_id}/messages)
- ✅ LLM-класифікатор (Anthropic Claude Haiku, 8 категорій)
- ✅ Роутинг за категорією: thanks/spam → no reply, spam → hide, complaint → Telegram
- ✅ Self-loop guard (не відповідаємо на власні коментарі)

**Reliability (17.0.3.x):**
- ✅ Exponential backoff retry на Graph API (1s/3s/9s)
- ✅ Audit log усіх Graph API calls у `ir.logging`
- ✅ PostgreSQL advisory lock на (contact_id, service) і comment_id (v17.0.3.7.1)
- ✅ Messenger 24h-window tracking + Telegram алерт за 2h до закриття
- ✅ Weekly token check cron для всіх Pages

**Multi-page FB/IG (17.0.3.7.0):**
- ✅ Модель `sendpulse.facebook.page` з Page Token + IG Business ID
- ✅ Resolve Page за webhook `page_id` у `_process_comment_event`
- ✅ Per-page URL overrides (landing/tg/yt)
- ✅ Settings кнопка «Синхронізувати з Meta /me/accounts»
- ✅ Token expiry check через `/debug_token` (потребує app_id+secret)

**Analytics (17.0.3.x):**
- ✅ Funnel metrics: `sp_funnel_stage` (7 stages)
- ✅ SLA: `sp_first_reply_time_sec` (computed stored)
- ✅ Link до `crm.lead` через `sp_lead_id`

**Escalation:**
- ✅ Telegram-алерти менеджерам (`_notify_telegram`)
- ✅ Події: complaint / hidden spam / 24h window / token expiry

### 1.2 Налаштовано на production (CampScout)

- ✅ SendPulse OAuth + webhook
- ✅ 11 FB Pages синхронізовані (CampScout default + 10 інших таборів)
- ✅ LLM-класифікатор активний
- ✅ Telegram-алерти активні (`@csodooalerts_bot` → CampScout.team)
- ✅ Cron-и працюють
- ✅ Meta App Review approved

### 1.3 Known limitations

- **FB Reel + private_reply** — Meta не підтримує `/private_replies` для коментарів під Reels. Для Reels працює лише публічна відповідь.
- **FB App Secret не налаштований** — cron каже `valid (no app_id/secret for expiry)` без точного `days_left`. Фікс: заповнити у Settings → Facebook App → App Secret.
- **Old deprecated ICP keys** — `ai_filter_enabled/ai_api_key/ai_base_url/ai_model` (стара Gemini binary класифікація) — у БД, але код їх ігнорує. Безпечно видалити.

---

## 2. Roadmap

### 2.1 Короткотермінові (до 2026-05-01)

| Задача | Статус | Залежності |
|---|---|---|
| Заповнити FB App ID + Secret | 🟡 pending | Потрібно від користувача |
| Long-lived token exchange через `/oauth/access_token` | 🟡 pending | Потрібно App Secret |
| Direct FB webhook як backup SendPulse | 🔴 відкладено | Низький пріоритет, SendPulse стабільний |

### 2.2 Середньо-термінові

- Автоматичне створення `crm.lead` з `sp_funnel_stage=lead_created`
- Dashboard з funnel-метриками (воронка + SLA per-operator)
- A/B-тест шаблонів публічних відповідей (вимірювати conversion rate `private_sent → customer_replied`)
- Multi-language класифікатор (зараз prompt UA, детектує всі але категорії узагальнені)

### 2.3 Довго-термінові

- Viber private messaging (SendPulse API не має прямої підтримки — через Botcenter)
- TikTok DM integration (обмежена доступність через Meta-conflict)
- Voice messages transcription (через Anthropic Speech API коли з'явиться)

---

## 3. Sub-TZs

Окремі детальні технічні завдання на конкретні фічі:

| TZ | Файл | Статус |
|---|---|---|
| Відповіді на коменти FB/IG | [TZ_COMMENT_AUTOREPLY.md](TZ_COMMENT_AUTOREPLY.md) | v1.4 — 8/10 done, 2 чекають Advanced Access |

Нові TZ додаються сюди у таблицю при початку роботи над фічею.

---

## 4. Критичні правила

### 4.1 Межі модуля

**⚠️ Зміни в SendPulse модулі ЛИШЕ за окремим ТЗ.** Інтеграція з Discuss/Omnichannel — у `omnichannel_bridge`. Порушення цього правила:

- `docs/CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md` — самовільна зміна SendPulse під час фіксу Discuss
- `docs/CRITICAL_INCIDENT_AI_UNAUTHORIZED_EDIT_SENDPULSE_CONNECT_2026-04-11.md` — зміни без письмового ТЗ

### 4.2 Git workflow

- **Ніколи** `git push --force` на main без згоди
- **Ніколи** `git commit --no-verify`
- Після `git pull` з auto-stash — **завжди** `git stash list` (2026-04-19 автостеш заховав цілий реліз; меморі/summary брехали)

### 4.3 Deploy safety

- **Не використовувати** `docker compose run --rm web` — зупиняє контейнер (INC 2026-04-13)
- Завжди `docker exec` на запущеному контейнері + `docker compose restart web`
- Після upgrade — перевіряти `SELECT latest_version FROM ir_module_module` (якщо модуль не завантажився — версія не оновиться, а UI може виглядати ок)

### 4.4 Secrets

- Токени → `ir.config_parameter` з `password="True"` у view
- `access_token` у audit log — `***REDACTED***`
- Ніколи не commit-ити реальні токени у git (gitignore: `*.env*`, `config/secret*`)

### 4.5 Стиль клієнтських повідомлень

Бачити `feedback_client_letters_style.md` у memory: коротко, по-людськи, без цитат пунктів договорів. Для публічних відповідей — 5 варіантів ротації в коді (`_COMMENT_PUBLIC_TEMPLATES`).

---

## 5. Архівні TZ (історія)

### v17.0.1.x (2026-03-26 — 2026-04-12)

- Базова ре-імплементація з ChatWoot → SendPulse
- Webhook від SendPulse, двостороння Discuss-інтеграція
- Auto-sync cron для втрачених контактів
- Bot-variables (`child_name`, `booking_email`)
- UTM source tracking per channel

### v17.0.2.x (2026-04-08 — 2026-04-15)

- `cron_pull_missing_contacts` (відновлення після downtime)
- Public User контамінація fixes (2026-04-13 + 2026-04-15)
- SQL міграції: разархівування каналів, зняття new_message при reply через webhook
- Rebrand: `SendPulse Odo` → `Fayna SendPulse Odo` у manifest

### v17.0.3.0 — 3.1 (2026-04-11 — 2026-04-20 вранці)

- `sp_is_comment` поле + перший draft comment processing
- IG comment detection через `media_product_type=FEED`
- Фікс 422-handler (парсинг `error_code:403` для Telegram-block vs Meta-24h)
- AI filter через Gemini (бінарний REPLY/SKIP) — знятий у v17.0.3.6.2 на користь Anthropic 8-категорного

### v17.0.3.2 — 3.6 (2026-04-19 стеш — 2026-04-20 розкриття)

⚠️ **Весь цей блок існував у `git stash auto-stash` від 2026-04-19 і був закоммічений тільки 2026-04-20**. Меморі/summary брехали про деплой — детальний розбір у LOG.md 2026-04-20. Включено:
- Retry + audit log
- LLM-класифікатор (Anthropic Haiku)
- Telegram-алерти
- 24h window tracking
- Funnel metrics
- Graph API v19 → v25

### v17.0.3.7.x (2026-04-20 вечір)

- Multi-page FB/IG refactor (11 Pages синхронізовано)
- Settings UI для LLM / Telegram / FB App / IG / Multi-page
- Race condition fix через `pg_advisory_xact_lock`
- 14 дублів на проді merged через одноразовий скрипт

---

## 6. Постмортеми

| Інцидент | Дата | Документ |
|---|---|---|
| AI intervention у SendPulse під час Discuss-фіксу | 2026-04-09 | `CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md` |
| AI password exposure | 2026-04-11 | `CRITICAL_INCIDENT_AI_PASSWORD_EXPOSURE_2026-04-11.md` |
| AI unauthorized edit sendpulse_connect.py | 2026-04-11 | `CRITICAL_INCIDENT_AI_UNAUTHORIZED_EDIT_SENDPULSE_CONNECT_2026-04-11.md` |

---

*Оновлюється при закритті кожного sprint/release. Джерело правди для roadmap-у модуля.*
