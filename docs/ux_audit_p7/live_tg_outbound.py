"""Живий Telegram-тест (Частина 3): вихідний напрямок.

Створює Telegram backend з тестовим токеном (з env TEST_TG_BOT_TOKEN),
надсилає реальне повідомлення через модуль і друкує результат.
Токен не друкується — лише факт.
"""

import os

token = os.environ.get('TEST_TG_BOT_TOKEN', '')
chat_id = os.environ.get('TEST_TG_CHAT_ID', '1216572335')

if not token:
    print('RESULT: FAIL — TEST_TG_BOT_TOKEN not set')
    raise SystemExit(1)

Backend = env['channel.backend'].sudo()

# Знайти або створити тестовий Telegram backend
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

# Реальний виклик Telegram API через модуль
text = 'FCB live test (outbound) — перевірка реального відклику Telegram API'
ok, provider_msg_id, err = backend.send_message(text, provider_user_id=chat_id)

if ok and provider_msg_id:
    print(f'RESULT: OUTBOUND OK — provider_message_id={provider_msg_id}')
    # Зафіксувати в журналі channel.message як доказ
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
else:
    print(f'RESULT: OUTBOUND FAIL — err={err}')
    raise SystemExit(1)
