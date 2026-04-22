# Odoo 17 SendPulse Integration — AI + Lead Magnet + Multi-Page FB/IG

![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20Community-purple)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Meta Graph](https://img.shields.io/badge/Meta%20Graph-v25.0-red)
![License](https://img.shields.io/badge/License-LGPL--3-green.svg)
![Status](https://img.shields.io/badge/Status-Production-brightgreen)

**Developed by [Fayna Digital](https://www.fayna.agency) for CampScout**
**Author: Volodymyr Shevchenko**

---

Two-way **SendPulse ↔ Odoo Discuss** bridge with operator-side AI assistant, lead magnet flow (PDF catalog + SMS coupon), live event seats awareness, drip campaigns, A/B template testing, auto-translation, and multi-page Facebook/Instagram support with LLM comment classification.

Reference deployment: [CampScout](https://campscout.eu) — child summer camps in Poland.

---

## Features

- **Unified inbox** — Telegram / Instagram / Facebook / Messenger / Viber / WhatsApp / LiveChat / TikTok all flow into single `mail.channel` in Odoo Discuss
- **Multi-page FB/IG** — 11 Facebook pages + 7 Instagram through System User tokens, Meta App Review approved 2026-04-20
- **AI operator assistant** — Claude Haiku 4.5 drafts replies in Discuss sidebar (OWL component)
- **Lead magnet flow** — email → branded PDF catalog; phone → SMS coupon from `loyalty.program` shared pool
- **Live event seats** — AI prompt receives real `seats_available` for each camp → honest FOMO or fallback messaging
- **Drip campaigns** — 6h / 24h reminders with cooldown and consent gating
- **A/B public templates** — epsilon-greedy selection with conversion tracking per variant
- **Auto-translation** — UA ↔ PL via Claude, inline in Discuss
- **FAQ RAG auto-answer** — Claude with confidence threshold auto-sends when safe
- **Comment classifier** — 8 categories (question, complaint, spam, praise, etc.) with LLM + Telegram alert routing
- **RODO/GDPR integration** — every consent event dual-written to `fayna.rodo.consent.log`

---

## Architecture

```
sendpulse-odoo/
├── models/
│   ├── sendpulse_connect.py           # Main model — one conversation per record (~4000 lines)
│   ├── sendpulse_message.py           # Per-message log
│   ├── sendpulse_facebook_page.py     # Multi-page FB/IG state
│   ├── sendpulse_faq_entry.py         # FAQ RAG knowledge base
│   ├── sendpulse_public_template.py   # A/B public templates + conversions
│   ├── sendpulse_identify_wizard.py   # Manual partner matching wizard
│   ├── sendpulse_privacy_consent_log.py  # Legacy consent log (dual-writes to fayna.rodo)
│   ├── res_config_settings.py         # Module settings
│   ├── res_partner.py                 # Partner extensions (UTM, channel history)
│   └── mail_channel.py                # Discuss channel extensions
├── controllers/
│   └── main.py                        # SendPulse webhook + Meta Graph callbacks
├── views/
│   ├── sendpulse_connect_views.xml    # Kanban, form, tree, Discuss sidebar
│   └── ...
├── data/
│   ├── sendpulse_data.xml             # Menu + actions
│   ├── sendpulse_faq_seed.xml         # Initial FAQ entries
│   ├── mail_template_lead_magnet.xml  # Branded lead magnet email
│   └── clean_data_cron.xml            # Scheduled cleanup
├── static/src/
│   ├── components/                    # OWL components (AI sidebar, info panel)
│   └── scss/
└── docs/
    ├── INDEX.md                        # Doc navigation
    ├── ARCHITECTURE.md
    ├── CONFIGURATION.md
    ├── DEPLOYMENT.md
    └── TZ_V2_AUTOMATION.md
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| ERP Framework | Odoo 17.0 Community |
| Core deps | `mail`, `contacts`, `crm`, `web`, `fayna_rodo_compliance` |
| Messaging provider | SendPulse Chatbot API + webhooks |
| Social graph | Meta Graph API v25.0 (via System User tokens) |
| AI | Claude Haiku 4.5 (Anthropic API) |
| SMS | TurboSMS (via `kw_sms_api`) |
| Retry strategy | Exponential backoff, ir.logging audit trail |
| Race-safety | PostgreSQL advisory lock + partial unique index |
| Module version | 17.0.14.0 |
| License | LGPL-3 |

---

## Installation

### 1. Clone into custom-addons

```bash
cd /opt/<client>/custom-addons
git clone https://github.com/VladSh77/fayna-sendpulse-odoo.git odoo_chatwoot_connector
```

> **Note:** technical directory name is `odoo_chatwoot_connector` for historical reasons (repo rename legacy). Odoo module technical name remains `odoo_chatwoot_connector` in manifest registration.

### 2. Install dependency

```bash
# Ensure fayna_rodo_compliance is installed first
docker exec <client>_web odoo -c /etc/odoo/odoo.conf -d <db> \
    -i fayna_rodo_compliance --stop-after-init --no-http
```

### 3. Install this module

```bash
docker exec <client>_web odoo -c /etc/odoo/odoo.conf -d <db> \
    -i odoo_chatwoot_connector --stop-after-init --no-http
```

Or via UI: **Apps → Update Apps List → search `SendPulse` → Install**.

### 4. Restart Odoo

```bash
docker restart <client>_web
```

---

## Configuration

### Step 1 — SendPulse credentials

1. Log in to [login.sendpulse.com](https://login.sendpulse.com) → **Settings → REST API**
2. Copy **ID** and **Secret**
3. In Odoo: **Settings → Technical → System Parameters** (requires developer mode):

| Key | Value |
|-----|-------|
| `sendpulse.api_id` | your SendPulse REST API ID |
| `sendpulse.api_secret` | your SendPulse REST API Secret |
| `sendpulse.webhook_secret` | random generated string (shared with webhook setup) |

### Step 2 — Webhook URL in SendPulse

In SendPulse dashboard → **Chatbot → Settings → Webhook**:

- URL: `https://<your-odoo>.com/sendpulse/webhook`
- Events: `income_message`, `outcome_message`, `bot_comment` (if using FB)

### Step 3 — Meta App for FB/IG (optional)

Follow [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for full Meta App Review flow with System User setup.

### Step 4 — AI credentials

| Key | Value |
|-----|-------|
| `sendpulse.anthropic_api_key` | Anthropic API key for Claude |
| `sendpulse.claude_model` | `claude-haiku-4-5-20251001` (default) |

### Step 5 — TurboSMS (for SMS coupons)

Configure `kw_sms_api` provider with TurboSMS credentials — see `campscout-management/docs/DEPLOYMENT.md`.

---

## Usage

### Operator receives chat

1. Customer writes to any connected channel (e.g. Telegram)
2. Webhook lands in `/sendpulse/webhook`
3. `sendpulse.connect` thread is created, bridged to `mail.channel`
4. Operator sees message in Odoo Discuss with partner card info
5. Operator replies — bridge sends through SendPulse API → back to Telegram

### Trigger lead magnet

1. Open `sendpulse.connect` record in sidebar panel
2. Click **Send PDF catalog** → prompts for email (or auto-fills if detected)
3. Module:
   - Sends branded PDF email via AWS SES
   - Records consent in `fayna.rodo.consent.log` with `purpose='lead_magnet_email'`
   - Updates chat with confirmation message

### AI draft replies

1. With developer-mode enabled, "Generate AI reply" button appears in Discuss sidebar
2. Claude Haiku receives:
   - Last 20 messages of conversation
   - Partner RFM segment
   - Live event seats context (FOMO messaging if < 30%)
   - FAQ RAG top-3 entries
3. Operator reviews, edits, sends

See [docs/TZ_V2_AUTOMATION.md](docs/TZ_V2_AUTOMATION.md) for all automation flows.

---

## RODO / GDPR Integration — Dual-Write

Every call to `sendpulse.privacy.consent.log.record_consent()` now **mirrors** into `fayna.rodo.consent.log` (generic horizontal model). This is **Phase 2 migration** to shared compliance infrastructure.

```python
# Internal flow, automatic:
legacy.record_consent(purpose='lead_magnet_email', channel='email', email=..., ...)
#   └── creates legacy sendpulse.privacy.consent.log record
#   └── ALSO creates mirror fayna.rodo.consent.log record
#       with evidence_model='sendpulse.message', evidence_id=msg.id
```

Future: will switch to reading consent solely from `fayna.rodo.consent.log` and deprecate legacy.

---

## Webhook Flow (technical)

```
1. SendPulse receives message from customer channel (Telegram/IG/FB/…)
2. POST https://<odoo>/sendpulse/webhook with signed payload
3. sendpulse/controllers/main.py:
   a. Verify signature (HMAC-SHA256 with webhook_secret)
   b. Deduplicate by (service + sendpulse_contact_id + timestamp)
   c. Advisory lock on (contact_id, service) to prevent race
4. Create or update sendpulse.connect record (thread)
5. Create sendpulse.message record (log)
6. Mirror to mail.channel (Discuss):
   a. If new contact — create channel
   b. Post message via mail.channel._message_post_feedback()
7. Trigger AI job if conditions met (e.g. FAQ match, drip schedule)
8. Return 200 OK
```

---

## Meta Graph API Flow (technical)

```
1. Customer comments on FB Page post
2. Page webhook subscription fires → /sendpulse/webhook/meta
3. Resolve page_access_token from sendpulse.facebook.page (11 pages live)
4. Fetch comment full body via Graph API v25.0
5. Classify with LLM (8 categories: question/spam/praise/…)
6. Route:
   - Category 'question' → auto-reply via Graph API send_message
   - Category 'spam' → hide comment
   - Category 'complaint' → Telegram alert to on-call manager
7. Log to ir.logging (audit trail)
```

---

## Local Development

```bash
git clone https://github.com/VladSh77/fayna-sendpulse-odoo.git
cd fayna-sendpulse-odoo

# Spin up ephemeral Odoo with this module mounted:
docker run -d --name test_odoo -v $(pwd)/..:/mnt/custom-addons \
    -p 8069:8069 odoo:17

# Mock SendPulse webhooks:
curl -X POST http://localhost:8069/sendpulse/webhook \
    -H "Content-Type: application/json" \
    -d '{"service": "telegram", "contact": {...}, "message": {...}}'
```

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for development secrets setup.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `ValueError: Invalid field 'sent_at' on model 'sendpulse.message'` | Historical bug — field is `date`, not `sent_at` | Fixed in v17.0.13.1; if seeing it — upgrade module |
| Signature verification fails | Webhook secret mismatch | Re-sync `sendpulse.webhook_secret` param ↔ SendPulse dashboard |
| Duplicate `sendpulse.connect` for same contact | Missing advisory lock / partial unique index | v17.0.10.x added `_sendpulse_dedup_idx`, ensure module upgrade ran |
| Meta Graph 401 error | System User token expired or page token revoked | Weekly cron checks tokens; re-authorize in Meta Business Settings |
| AI sidebar not rendering in Discuss | OWL asset bundle cached | Hard refresh (Ctrl+Shift+R); if persists — regenerate bundle via `odoo shell` → `self.env['ir.qweb']._clear_cache()` |
| Lead magnet email not sent | AWS SES sandbox (only verified recipients) | Request SES production access; or whitelist recipients |
| `fayna.rodo.consent.log` not created during dual-write | Dependency not installed | Install `fayna_rodo_compliance` first |

---

## Operator Access

Standard Odoo Discuss access model — no module-specific group required. All users with `mail.group_user` can:

- See inbox of connected channels
- Reply in threads
- View partner sidebar panel

**Module admin** (`group_omnichannel_admin` in `sendpulse-odoo`) additionally:

- Configure SendPulse credentials
- Manage FB/IG pages
- Edit FAQ entries
- View LLM audit logs

---

## Module Ecosystem

This module is part of Fayna Digital Odoo stack:

| Sibling module | Relationship |
|----------------|--------------|
| [fayna-rodo-compliance](https://github.com/VladSh77/fayna-rodo-compliance) | **Required dependency** — consent logging |
| [omnichannel-bridge](https://github.com/VladSh77/omnichannel-bridge) | Abstract messenger aggregator — sendpulse-odoo is one adapter |
| [zadarma-odoo](https://github.com/VladSh77/zadarma-odoo) | Voice channel (complements messenger) |
| [campscout-management](https://github.com/VladSh77/campscout-management) | Vertical CampScout layer — uses sendpulse-odoo for all chat flows |

Architecture docs: [fayna-digital-docs](https://github.com/VladSh77/fayna-digital-docs) (private).

---

## License

LGPL-3 — see [LICENSE](LICENSE)

---

*Developed by [Fayna Digital](https://www.fayna.agency) · Volodymyr Shevchenko*
