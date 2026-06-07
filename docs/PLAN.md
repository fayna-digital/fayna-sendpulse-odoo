# PLAN — sendpulse-odoo (план реалізації)

> Друга черга після docs/TZ.md. Базовий функціонал (11 фіч V2, comment autoreply, RODO) — на проді. Деталі фіч → docs/TZ_V2_AUTOMATION.md. Що зроблено → CHANGELOG.md.

## Dependency graph

```
[tests/] ── незалежний ── критичний (5.5K рядків ядра без покриття)
[FB App Secret] → [Long-lived token 365d] → [token auto-refresh F6 повний]
[Multi-language LLM] ── на базі UA-класифікатора ── розширення
[version/doc sync] ── косметика
```

## Task List

### Phase 1: Safety net (критичне)

- [ ] **tests/** — ядро `sendpulse_connect.py` (5.5K рядків) без жодного тесту
  - Acceptance (з TZ_V2 §6 DoD): RAG retrieval, template picker, auto-lead (F4), token exchange (F6), webhook→connect, Discuss sync, Meta retry, comment→reply funnel; ≥70%
  - Files: `tests/test_*.py`

### Checkpoint: Phase 1
Критичні методи покриті, тести зелені.

### Phase 2: Meta/токени

- [ ] **FB App Secret заповнення** → `debug_token` + auto-refresh
- [ ] **Long-lived token exchange 365d+** (чекає FB App Secret)
- [ ] **Direct FB webhook** як backup SendPulse (низький пріоритет)

### Phase 3: Розширення

- [ ] **Multi-language LLM-класифікатор** коментарів (зараз UA-only)
- [ ] **Voice transcription** (Anthropic Speech API, коли доступне)
- [ ] Viber private / TikTok DM — обмеження SendPulse/Meta API (моніторити)

### Phase 4: Документаційний борг

- [ ] Синхронізувати версії в усіх доках на 14.7 (manifest) — частково (TZ зроблено)
- [ ] TZ_V2_AUTOMATION → позначити фічі completed (вже в CHANGELOG)
- [ ] CHANGELOG — дописати v14.5/14.6/14.7 (зараз до 14.4)
- [ ] 3 CRITICAL_INCIDENT post-mortems → правила вже в TZ Boundaries; звести в один INCIDENTS.md

## Зв'язки
docs/TZ.md · docs/TZ_V2_AUTOMATION.md · [[REPO_STANDARD]] · [[projects/kanban]]
