# Seed тестових каналів для скрінів Е-1 (список «Канали» + форма).
# Запуск: docker exec -i fayna_bridge_test_web odoo shell -d fayna_bridge_test < seed_e1.py
Backend = env['channel.backend']  # noqa: F821
NI = Backend._HEALTHCHECK_NOT_IMPLEMENTED

# Прибрати попередні seed-канали (якщо є), щоб список був чистим.
existing = Backend.search([('name', 'like', 'E1-')])
if existing:
    existing.unlink()

# 1. Вимкнено
Backend.create(
    {
        'name': 'E1-Вимкнено',
        'service': 'telegram',
        'provider': 'direct',
        'active': False,
        'last_healthcheck_ok': False,
        'last_error': 'Канал вимкнено вручну',
    }
)
# 2. Працює
Backend.create(
    {
        'name': 'E1-Працює',
        'service': 'telegram',
        'provider': 'direct',
        'active': True,
        'last_healthcheck_ok': True,
        'last_error': '',
    }
)
# 3. Перевірка не підтримується
Backend.create(
    {
        'name': 'E1-Не підтримується',
        'service': 'viber',
        'provider': 'direct',
        'active': True,
        'last_healthcheck_ok': False,
        'last_error': NI,
    }
)
# 4. Помилка
Backend.create(
    {
        'name': 'E1-Помилка',
        'service': 'whatsapp',
        'provider': 'direct',
        'active': True,
        'last_healthcheck_ok': False,
        'last_error': '401 Unauthorized: невалідний токен',
    }
)

for b in Backend.search([('name', 'like', 'E1-')], order='name'):
    print(
        'SEED',
        b.name,
        '| active=',
        b.active,
        '| ok=',
        b.last_healthcheck_ok,
        '| state=',
        b.state,
    )
env.cr.commit()  # noqa: F821
print('SEED_DONE')
