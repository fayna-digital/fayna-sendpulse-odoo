# Fayna SendPulse Odoo — Docs Index

Швидкий entry-point. Всі документи живуть у `docs/` цього репо; platform-wide документи — у `fayna-digital-docs` на GitHub.

## Start here

- **[../README.md](../README.md)** — overview + quickstart
- **[../CHANGELOG.md](../CHANGELOG.md)** — versions history
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — technical architecture
- **[CONFIGURATION.md](CONFIGURATION.md)** — configuration guide
- **[DEPLOYMENT.md](DEPLOYMENT.md)** — deployment procedure
- **Platform context:** [fayna-digital-docs](https://github.com/VladSh77/fayna-digital-docs) (private)
  - [ADR-002 horizontal+feature decomp](https://github.com/VladSh77/fayna-digital-docs/blob/main/adr/ADR-002-horizontal-plus-feature-decomp.md)
  - [ADR-003 adapter pattern](https://github.com/VladSh77/fayna-digital-docs/blob/main/adr/ADR-003-adapter-pattern.md) — sendpulse-odoo = adapter для `fayna_omnichannel_bridge`
  - [OVERVIEW](https://github.com/VladSh77/fayna-digital-docs/blob/main/architecture/OVERVIEW.md) — картина всього Fayna stack

## TZ (technical specifications)

- **[TZ.md](TZ.md)** — главна ТЗ
- **[TZ_V2_AUTOMATION.md](TZ_V2_AUTOMATION.md)** — V2 automation specs (F2-F14 фічі)
- **[TZ_COMMENT_AUTOREPLY.md](TZ_COMMENT_AUTOREPLY.md)** — auto-reply flow на коментарі
- **[TZ_F4_ENABLE_LEAD.md](TZ_F4_ENABLE_LEAD.md)** — F4 chat→лід (авто-crm.lead, пул+claim, увімкнено 2026-06-18)
- **[TZ_I18N_DATA.md](TZ_I18N_DATA.md)** — i18n даних/повідомлень

## Incident reports (historical)

- **[CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md](CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md)**
- **[CRITICAL_INCIDENT_AI_PASSWORD_EXPOSURE_2026-04-11.md](CRITICAL_INCIDENT_AI_PASSWORD_EXPOSURE_2026-04-11.md)**
- **[CRITICAL_INCIDENT_AI_UNAUTHORIZED_EDIT_SENDPULSE_CONNECT_2026-04-11.md](CRITICAL_INCIDENT_AI_UNAUTHORIZED_EDIT_SENDPULSE_CONNECT_2026-04-11.md)**

Всі — lessons learned; post-mortem у кожному файлі.

## Relationship з іншими Fayna-модулями

- **depends on:** `fayna_rodo_compliance` (consent logging)
- **architecturally adapter for:** `fayna_omnichannel_bridge` (бере abstract contracts, реалізує SendPulse-specific)
- **complements:** `campscout_management` (CampScout lead magnet flow)

---

## Як знайти потрібне

- **Нова людина:** ARCHITECTURE.md → CONFIGURATION.md
- **Debug живого incident:** CRITICAL_INCIDENT_*.md — дивись schema, чи не повторюється
- **RODO-question:** `fayna_rodo_compliance/docs/RUNBOOK.md` — dual-write контекст описаний там
- **Нові features:** TZ_V2_AUTOMATION.md
- **docs/TZ_I18N_DATA.md** — ТЗ: i18n даних/клієнтських повідомлень за стандартами Odoo (чернетка)
