# TZ — sendpulse-odoo

> Специфікація за [[REPO_STANDARD]] (6 областей spec-driven). Як працювати → CLAUDE.md.
> Версія: **17.0.1.15.13** | License: LGPL-3. Під-ТЗ: docs/TZ_COMMENT_AUTOREPLY.md (виконано), docs/TZ_V2_AUTOMATION.md (фічі).

---

## 1. Objective

**Що:** omnichannel-міст **SendPulse ↔ Odoo 17 Discuss** + AI-асистент. Двостороння синхронізація чатів (Telegram/IG/FB/Messenger/Viber/WhatsApp/LiveChat/TikTok), авто-ідентифікація контактів, черга pickup, UTM, FB/IG коментарі з автовідповіддю, AI-драфти (Claude Haiku), lead magnet (PDF+SMS), drip-кампанії, A/B шаблони, RODO audit.

**Для кого:** CampScout (дитячі літні табори PL), Fayna Digital.

**Версія/license:** 17.0.1.15.13, LGPL-3. **Depends:** `mail`, `contacts`, `crm`, `web` + python `requests`. Meta Graph API v25.0, Anthropic API (Claude).

**Успіх:** вхідні з усіх каналів з'являються в Discuss з ідентифікованим контактом; коментарі FB/IG отримують автовідповідь; менеджер бачить AI-драфт; RODO-згоди логуються.

**Технології:** [[library/tools/python]] · Odoo 17 · [[library/tools/postgresql]] · SendPulse API · Meta Graph API · Anthropic Claude · [[library/tools/sendpulse]].

---

## 2. Commands

```bash
# Deploy / update (docker exec на ЗАПУЩЕНОМУ — НЕ docker compose run --rm)
git push origin main
ssh prod 'cd /opt/campscout/custom-addons/odoo_chatwoot_connector && git pull && sudo chmod -R o+rX .'
ssh prod 'docker exec campscout_web odoo -c /etc/odoo/odoo.conf -d campscout -i odoo_chatwoot_connector --stop-after-init && docker restart campscout_web'

# Перевірка версії після оновлення
# SELECT latest_version FROM ir_module_module WHERE name='odoo_chatwoot_connector';

# Lint
ruff check . && ruff format --check .

# Тести (⚠️ tests/ порожня — реалізувати)
python -m pytest tests/ -v
```

---

## 3. Project Structure

```
sendpulse-odoo/
  models/
    sendpulse_connect.py        # ядро 5.5K рядків — інтеграція, webhook, AI, 91 метод
    sendpulse_message.py        # журнал повідомлень
    sendpulse_facebook_page.py  # multi-page state (FB/IG)
    sendpulse_faq_entry.py      # F1 RAG FAQ
    sendpulse_public_template.py# F9 A/B шаблони
    sendpulse_identify_wizard.py# F3 bot-ID
    sendpulse_privacy_consent_log.py # RODO audit (дзеркало → fayna_rodo_compliance)
    res_config_settings.py / res_partner.py / mail_channel.py
  controllers/
    main.py                     # webhook handler
    meta_lead_webhook.py        # Meta Lead webhook
  data/  views/(8)  security/  static/src/components/sendpulse_info_panel/
  docs/  i18n/
```

Детально: **docs/ARCHITECTURE.md** · **docs/CONFIGURATION.md** · **docs/DEPLOYMENT.md**.

---

## 4. Code Style

- Python 3.10+, Odoo 17 ORM (`fields.*`, `@api.depends`), UTC timestamps
- Українські labels; англ. docstrings, укр. коментарі
- Токени → `ir.config_parameter` (`password="True"`), audit-лог з `***REDACTED***`
- Webhook оновлює поля через `sudo()` (public auth); `UserError`/`IntegrityError`
- PostgreSQL advisory lock + race-safe unique index для дедуплікації
- ⚠️ GAP: немає type hints, частина методів `sendpulse_connect.py` без docstring

---

## 5. Testing Strategy

- **Фреймворк:** pytest, `tests/`
- ⚠️ **GAP: тести відсутні** (папка порожня). Пріоритет (з TZ_V2 §6 DoD): RAG retrieval, template picker (epsilon-greedy), auto-create lead (F4), token exchange (F6), webhook→connect, Discuss sync, Meta retry, comment→reply funnel.

---

## 6. Boundaries

**Always:**
- Деплой #4ZONES: локально → GitHub → staging → prod (golden rule #3)
- `docker exec` на запущеному (НЕ `docker compose run --rm` — зупиняє контейнер)
- Після `git pull` → `git stash list` (інцидент 2026-04-19)

**Ask first:**
- Будь-яка зміна SendPulse-модуля — **лише за окремим ТЗ**
- Додавання каналів / зміна Meta Graph API версії

**Never:**
- Чіпати SendPulse під час робіт над Discuss/омніканал (інцидент 2026-04-09 — AI самовільно змінила)
- Редагувати на сервері напряму; секрети (SendPulse/FB/Anthropic) у код/чат/лог
- Force push на main, `--no-verify`

---

## Success Criteria

- [x] Comment autoreply FB/IG (v17.0.3.7.1, TZ_COMMENT_AUTOREPLY 10/10 DoD)
- [x] V2 automation 11 фіч (F1-F14 у CHANGELOG v17.0.5-12)
- [x] RODO consent log (v17.0.13.0)
- [x] Multi-page FB/IG (System User)
- [ ] tests/ ≥70%
- [ ] Long-lived token 365d (чекає FB App Secret)
- [ ] Multi-language LLM-класифікатор (зараз UA-only)

---

## Open Questions
- **Version mismatch:** manifest 14.7 vs стара шапка TZ 3.7.1 vs CHANGELOG 14.4 — синхронізувати (виправлено в цьому TZ на 14.7).
- TZ_V2_AUTOMATION — фічі вже реалізовані (CHANGELOG), документ-план застарів → позначити completed.
- 3 CRITICAL_INCIDENT post-mortems → винести правила в Boundaries (частково зроблено тут).

## Зв'язки
[[REPO_STANDARD]] · docs/PLAN.md · docs/TZ_V2_AUTOMATION.md · docs/ARCHITECTURE.md · [[claude-memory/project_sendpulse_pl_messenger_webhook_2026-05-29]] · [[library/tools/sendpulse]] · Repo: `VladSh77/sendpulse-odoo`
