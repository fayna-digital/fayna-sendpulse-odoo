# CHANGELOG — odoo-chatwoot-connector (SendPulse Connector)

Формат: `## [date] — YYYY-MM-DD`

---

## [2026-04-03]

- Docs: professional badges, author attribution, Fayna Digital branding

## [2026-04-02]

- Docs: session 6 log — stage fix, channel stats, orphan attachments cleanup
- Fix: очищення stage 'new_message' коли оператор відповідає через SendPulse webhook

## [2026-03-29]

- Fix: запобігання дублюванню WhatsApp / Telegram каналів при повторному контакті
- Fix: тип `photo` для Telegram image messages у SendPulse API
- Fix: вкладення не прив'язані до mail.message — видалено `res_model` при створенні
- Docs: виправлено deploy path — Docker монтує `/opt/campscout/custom-addons`
- Fix: завантаження SendPulse media через API, збереження як Odoo attachment
- Fix: рендеринг вхідних медіа (зображення, стікери, лайки) як `<img>` у Discuss
- Fix: href extraction — пошук атрибута незалежно від порядку у тезі `<a>`
- Fix: crash на `action_close` — прибрано confirm dialog, додано reload
- Fix: коректний рендеринг URL при відправці посилань операторами

## [2026-03-28]

- Fix: settings cloud icon (dirty state) + saved indicator
- Docs: session 5 log як incident timeline table
- Docs: всі 4 канали підтверджено як working
- Fix: WhatsApp message format — `text.body` nested object
- Fix: Messenger і WhatsApp payload format

## [2026-03-27]

- Docs: TECHNICAL_DOCS — session 4 log, нові функції, фікси
- Chore: автор Fayna, module description page
- Fix: поле Operators — тільки internal users

## [2026-03-26] — Ранні версії

- Feat: двостороння переписка (Odoo Discuss ↔ SendPulse API)
- Feat: webhook endpoint `POST /sendpulse/webhook`
- Feat: ідентифікація клієнтів (email / телефон → `res.partner`)
- Feat: черга неідентифікованих чатів
- Feat: UTM-атрибуція першого контакту
- Feat: підтримка каналів: Telegram, Instagram, Facebook, Viber, WhatsApp, TikTok
- Feat: `sendpulse.webhook.data` — сирі дані (7-денна ротація)
- Feat: розмежування доступу Officer / Administrator
