"""Живий Telegram-тест (Частина 3): вхідний напрямок — налаштування webhook.

Встановлює web.base.url на адресу тунелю і реєструє webhook тестового бота.
Токен не друкується.
"""

import os

token = os.environ.get('TEST_TG_BOT_TOKEN', '')
tunnel_url = os.environ.get('TEST_TG_TUNNEL_URL', '')

if not token:
    print('RESULT: FAIL — TEST_TG_BOT_TOKEN not set')
    raise SystemExit(1)
if not tunnel_url:
    print('RESULT: FAIL — TEST_TG_TUNNEL_URL not set')
    raise SystemExit(1)

# 1. Встановити web.base.url на адресу тунелю
ICP = env['ir.config_parameter'].sudo()
ICP.set_param('web.base.url', tunnel_url)
print(f'RESULT: web.base.url set to {tunnel_url}')

# 2. Знайти тестовий backend і зареєструвати webhook
Backend = env['channel.backend'].sudo()
backend = Backend.search([('service', '=', 'telegram'), ('bot_token', '=', token)], limit=1)
if not backend:
    print('RESULT: FAIL — backend not found')
    raise SystemExit(1)

webhook_url, err = backend.register_telegram_webhook()
if webhook_url:
    print(f'RESULT: WEBHOOK REGISTERED — url={webhook_url}')
    print(f'RESULT: webhook_path_id={backend.webhook_path_id}')
else:
    print(f'RESULT: WEBHOOK FAIL — err={err}')
    raise SystemExit(1)
