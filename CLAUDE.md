# Fayna SendPulse — CLAUDE.md

> 🚫 **#4ZONES — НІКОЛИ не працювати напряму на сервері.** Локально → GitHub (push) → staging → prod (pull). Жодних правок файлів/скриптів на сервері. Git — єдине джерело правди. ([[meta/golden-rules-developer]] #3)
> **Що** будуємо → [docs/TZ.md](docs/TZ.md) (6 областей за REPO_STANDARD).

## Призначення

Omnichannel-міст **SendPulse ↔ Odoo 17 Discuss** + AI-асистент для CampScout. Канали: Telegram, Instagram, Facebook/Messenger, Viber, WhatsApp, LiveChat, TikTok. Авто-ідентифікація контактів, черга pickup, UTM-атрибуція, FB/IG коментарі з автовідповіддю, AI-драфти (Claude), lead magnet, drip-кампанії, RODO audit.

**Версія:** `17.0.14.7` | License: LGPL-3 | **Depends:** `mail`, `contacts`, `crm`, `web` + python `requests`

## Ключові файли

| Файл | Що робить |
|------|-----------|
| `models/sendpulse_connect.py` | ядро (5.5K рядків) — інтеграція, webhook-логіка, AI |
| `models/mail_channel.py` | override `_channel_info` (Odoo 17) |
| `models/sendpulse_faq_entry.py` | RAG FAQ (F1) |
| `models/sendpulse_public_template.py` | A/B шаблони (F9) |
| `models/sendpulse_privacy_consent_log.py` | RODO audit (дзеркало → fayna_rodo_compliance) |
| `controllers/main.py` | webhook handler |
| `controllers/meta_lead_webhook.py` | Meta Lead webhook |

## Deploy — #4ZONES

```bash
git push origin main
ssh prod 'cd /opt/campscout/custom-addons/odoo_chatwoot_connector && git pull && sudo chmod -R o+rX .'
# update (docker exec на ЗАПУЩЕНОМУ, НЕ docker compose run --rm — він зупиняє контейнер):
ssh prod 'docker exec campscout_web odoo -c /etc/odoo/odoo.conf -d campscout -u odoo_chatwoot_connector --stop-after-init && docker restart campscout_web'
# Перевірка що оновилось:
# SELECT latest_version FROM ir_module_module WHERE name='...';
```

## Секрети (КРИТИЧНО)

- SendPulse API ID+Secret, Facebook Page Token, Anthropic API Key → `ir.config_parameter` (`password="True"`)
- **НІКОЛИ** не комітити токени в git/CHANGELOG; audit-лог з `***REDACTED***`
- `.gitignore` покриває `*.env*`, `secret*`, `MEMORY.md`

## Coding conventions

- Python 3.10+, Odoo 17 ORM, UTC timestamps, `_logger`
- Токени тільки в `ir.config_parameter` (password=True)
- Webhook оновлює поля через `sudo()` (public auth)
- Git: **ніколи** force push на main / `--no-verify`; після `git pull` → `git stash list` (інцидент 2026-04-19: autostash заховав реліз)

## Межі (#BOUNDARY)

- SendPulse модуль чіпати **лише за окремим ТЗ**. Інтеграція з Discuss/омніканал → `omnichannel_bridge`.
- ⚠️ Інцидент 2026-04-09: AI самовільно змінила SendPulse під час фіксу Discuss — **заборонено**.

## Документація

- **docs/TZ.md** — специфікація (6 областей) ← REPO_STANDARD
- **docs/PLAN.md** — план фаз
- **docs/TZ_COMMENT_AUTOREPLY.md** (виконано v1.4) · **docs/TZ_V2_AUTOMATION.md** (11 фіч)
- **docs/ARCHITECTURE.md** / **CONFIGURATION.md** / **DEPLOYMENT.md** · **CHANGELOG.md**
- **docs/CRITICAL_INCIDENT_*.md** — 3 post-mortems

## Зв'язки
[[REPO_STANDARD]] · [[library/tools/python]] · [[library/tools/postgresql]] · [[claude-memory/project_sendpulse_pl_messenger_webhook_2026-05-29]] · [[meta/golden-rules-developer]]
