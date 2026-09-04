"""Живий Telegram-тест (Частина 3): повний цикл в одній сесії.

1. Створює Telegram backend з тестовим токеном.
2. Вихідний напрямок: send_message → реальний відклик Telegram API.
3. Вхідний напрямок: встановлює web.base.url на тунель і реєструє webhook.
Кожен крок комітиться. Токен не друкується.
"""

import os

token = os.environ.get('TEST_TG_BOT_TOKEN', '')
chat_id = os.environ.get('TEST_TG_CHAT_ID', '1216572335')
tunnel_url = os.environ.get('TEST_TG_TUNNEL_URL', '')

if not token:
    print('RESULT: FAIL — TEST_TG_BOT_TOKEN not set')
    raise SystemExit(1)

Backend = env['channel.backend'].sudo()

# ── 1. Створити (або знайти) тестовий Telegram backend ──
backend = Backend.search([('service', '=', 'telegram'), ('bot_token', '=', token)], limit=1)
if not backend:
    backend = Backend.create(
        {
            'name': 'FCB Live Test (Telegram)',
            'service': 'telegram',
            'provider': 'direct',
            'transport_priority': 'own',
            'bot_token': token,
            'bot_id': '@camp_odoo_bot',
            'active': True,
        }
    )
    print(f'RESULT: backend created id={backend.id}')
else:
    print(f'RESULT: backend found id={backend.id}')
env.cr.commit()

# ── 2. Вихідний напрямок: реальний sendMessage ──
text = 'FCB live test (outbound) — перевірка реального відклику Telegram API'
ok, provider_msg_id, err = backend.send_message(text, provider_user_id=chat_id)
if ok and provider_msg_id:
    print(f'RESULT: OUTBOUND OK — provider_message_id={provider_msg_id}')
    msg = (
        env['channel.message']
        .sudo()
        .create(
            {
                'backend_id': backend.id,
                'service': 'telegram',
                'direction': 'outgoing',
                'state': 'sent',
                'provider_message_id': provider_msg_id,
                'provider_user_id': chat_id,
                'text_message': text,
            }
        )
    )
    print(
        f'RESULT: channel.message id={msg.id} state={msg.state} provider_message_id={msg.provider_message_id}'
    )
    env.cr.commit()
else:
    print(f'RESULT: OUTBOUND FAIL — err={err}')
    raise SystemExit(1)

# ── 3. Вхідний напрямок: webhook на тунель ──
if tunnel_url:
    ICP = env['ir.config_parameter'].sudo()
    ICP.set_param('web.base.url', tunnel_url)
    print(f'RESULT: web.base.url set to {tunnel_url}')
    env.cr.commit()

    webhook_url, werr = backend.register_telegram_webhook()
    if webhook_url:
        print(f'RESULT: WEBHOOK REGISTERED — url={webhook_url}')
        print(f'RESULT: webhook_path_id={backend.webhook_path_id}')
        env.cr.commit()
    else:
        print(f'RESULT: WEBHOOK FAIL — err={werr}')
        raise SystemExit(1)
else:
    print('RESULT: INBOUND SKIPPED — no tunnel URL')
