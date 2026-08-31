#!/usr/bin/env python3
"""
Міграція даних: sendpulse_connect → channel.conversation / channel.backend / channel.message.

УВАГА: це РУЧНИЙ одноразовий скрипт (не автоматична Odoo-міграція). Він лежить
у tools/ поза каталогом модуля, бо не відповідає схемі migrations/<version>/ і
Odoo його ніколи не виконає сам. Запускається вручну через `odoo shell` на
staging/prod ПІСЛЯ встановлення модуля fayna_channel_bridge. Він переносить
історію розмов зі старої моделі SendPulse (sendpulse_connect) у нову автономну
модель власного транспорту.

Що робить:
  1. Створює channel.backend на кожен service (без credentials — токени
     налаштовуються окремо, див. аудит безпеки).
  2. Створює channel.conversation з sendpulse_connect (1:1), зберігаючи
     зв'язок з існуючим discuss.channel (channel_id) — історія переписок
     (mail.message) залишається на місці.
  3. Сіє summary-запис у channel.message на кожну розмову (журнал нового
     транспорту), НЕ дублюючи всі 22k повідомлень — вони лишаються в discuss.channel.

Ідемпотентність: скрипт безпечно перезапускати — повторні запуски не
створюють дублікатів (перевірка за provider_user_id + service).

Запуск (з контейнера odoo):
    docker exec campscout_web odoo shell -c /etc/odoo/odoo.conf -d campscout \
        --no-http < migrations/migrate_sendpulse_to_channel.py
"""

import logging

_logger = logging.getLogger('fayna_channel_bridge.migration')

# Префікс для provider_user_id, який ми беремо з sendpulse_contact_id.
# Це НЕ нативний ID провайдера (chat_id/PSID), а внутрішній ID SendPulse.
# Префікс запобігає колізії з нативними ID, коли нові webhook-и почнуть
# створювати розмови з реальними provider_user_id.
SP_ID_PREFIX = 'sp:'

# Мапа stage sendpulse_connect → channel.conversation (значення збігаються 1:1).
STAGE_MAP = {
    'new': 'new',
    'new_message': 'new_message',
    'in_progress': 'in_progress',
    'close': 'close',
}


def _run(env):
    """Виконує міграцію. Повертає dict зі статистикою."""
    stats = {'backends': 0, 'conversations': 0, 'messages': 0, 'skipped': 0}

    # ── 1. Перевірка наявності джерела ──────────────────────────────────
    if 'sendpulse.connect' not in env:
        _logger.warning('Модель sendpulse.connect не знайдена — міграція не потрібна.')
        return stats

    Source = env['sendpulse.connect'].sudo()
    Backend = env['channel.backend'].sudo()
    Conversation = env['channel.conversation'].sudo()
    Message = env['channel.message'].sudo()

    total = Source.search_count([])
    if total == 0:
        _logger.info('sendpulse_connect порожня — міграція не потрібна.')
        return stats

    _logger.info('Міграція: %s записів sendpulse_connect → channel.conversation', total)

    # ── 2. Створюємо channel.backend на кожен service ───────────────────
    services = Source.read_group([], ['service'], groupby=['service'])
    backend_by_service = {}
    for grp in services:
        service = grp['service']
        if not service:
            continue
        existing = Backend.search([('service', '=', service), ('provider', '=', 'direct')], limit=1)
        if existing:
            backend_by_service[service] = existing.id
            continue
        backend = Backend.create(
            {
                'name': f'{service.capitalize()} (migrated)',
                'service': service,
                'provider': 'direct',
                'transport_priority': 'auto',
                'active': True,
            }
        )
        backend_by_service[service] = backend.id
        stats['backends'] += 1

    # ── 3. Мігруємо розмови ─────────────────────────────────────────────
    # Обробляємо батчами, щоб не тримати всі 1069 у пам'яті.
    BATCH = 200
    offset = 0
    while True:
        sources = Source.search([], order='id asc', limit=BATCH, offset=offset)
        if not sources:
            break
        for src in sources:
            service = src.service or ''
            sp_id = (src.sendpulse_contact_id or '').strip()
            channel_id = src.channel_id.id if src.channel_id else False

            # Базовий provider_user_id з sendpulse_contact_id.
            # Це НЕ нативний ID провайдера, а внутрішній ID SendPulse.
            base_provider_user_id = f'{SP_ID_PREFIX}{sp_id}' if sp_id else ''

            # Один і той самий контакт (sendpulse_contact_id) може мати КІЛЬКА
            # розмов у різних discuss.channel (channel_id). Щоб не втратити
            # історію жодної з них, створюємо окрему channel.conversation на
            # кожен унікальний (contact, service, channel_id).
            #
            # Унікальний індекс channel_conversation_active_provider_uniq
            # обмежує (provider_user_id, service) для активних записів, тому
            # для повторних (contact, service) з іншим channel_id додаємо
            # суфікс ":<channel_id>" до provider_user_id.
            provider_user_id = base_provider_user_id
            if base_provider_user_id:
                existing_same = Conversation.search(
                    [
                        ('provider_user_id', '=', base_provider_user_id),
                        ('service', '=', service),
                    ],
                    limit=1,
                )
                if existing_same:
                    # Цей (contact, service) вже має розмову. Якщо це той самий
                    # channel_id — це повторний запуск, пропускаємо.
                    if existing_same.channel_id.id == channel_id:
                        stats['skipped'] += 1
                        continue
                    # Інший channel_id — унікалізуємо provider_user_id суфіксом.
                    provider_user_id = f'{base_provider_user_id}:{channel_id}'

            # Ідемпотентність: пропускаємо, якщо саме ця розмова вже мігрована
            # (перевірка за унікалізованим provider_user_id + service).
            if provider_user_id:
                existing = Conversation.search(
                    [
                        ('provider_user_id', '=', provider_user_id),
                        ('service', '=', service),
                    ],
                    limit=1,
                )
                if existing:
                    stats['skipped'] += 1
                    continue

            vals = {
                'name': src.name or 'Невідомий',
                'service': service,
                'backend_id': backend_by_service.get(service, False),
                'channel_id': src.channel_id.id if src.channel_id else False,
                'partner_id': src.partner_id.id if src.partner_id else False,
                'provider_user_id': provider_user_id,
                'provider_bot_id': (src.bot_id or '').strip() or False,
                'bot_name': (src.bot_name or '').strip() or False,
                'active': bool(src.active),
                'stage': STAGE_MAP.get(src.stage, 'new'),
                'transport': 'own',
                'social_username': (src.social_username or '').strip() or False,
                'social_profile_url': (src.social_profile_url or '').strip() or False,
                'last_message_preview': (src.last_message_preview or '')[:100] or False,
                'last_message_date': src.last_message_date or False,
            }
            conv = Conversation.create(vals)
            # Зберігаємо оригінальні дати створення/зміни.
            if src.create_date:
                env.cr.execute(
                    'UPDATE channel_conversation SET create_date=%s WHERE id=%s',
                    (src.create_date, conv.id),
                )
            if src.write_date:
                env.cr.execute(
                    'UPDATE channel_conversation SET write_date=%s WHERE id=%s',
                    (src.write_date, conv.id),
                )
            stats['conversations'] += 1

            # ── 4. Summary-запис у channel.message ──────────────────────
            if src.last_message_preview or src.last_message_date:
                Message.create(
                    {
                        'backend_id': backend_by_service.get(service, False),
                        'service': service,
                        'direction': 'incoming',
                        'state': 'received',
                        'provider_user_id': provider_user_id,
                        'text_message': (f"[migrated] {src.last_message_preview or ''}"[:500]),
                        'date': src.last_message_date or src.create_date,
                    }
                )
                stats['messages'] += 1

        offset += BATCH
        env.cr.commit()
        _logger.info('Міграція: оброблено %s/%s', min(offset, total), total)

    env.cr.commit()
    _logger.info(
        'Міграція завершена: backends=%s conversations=%s messages=%s skipped=%s',
        stats['backends'],
        stats['conversations'],
        stats['messages'],
        stats['skipped'],
    )
    return stats


# Точка входу для `odoo shell`.
# `env` інжектується середовищем `odoo shell` як глобал (не визначений статично).
if __name__ == '__main__':
    result = _run(env)  # noqa: F821
    print('MIGRATION_RESULT:', result)
