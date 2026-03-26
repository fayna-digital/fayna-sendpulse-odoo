# -*- coding: utf-8 -*-
{
    'name': 'SendPulse Odo',
    'version': '17.0.1.0.0',
    'summary': 'Інтеграція SendPulse з Odoo — зберігання чатів у картці клієнта',
    'description': """
        Двостороння інтеграція між Odoo і SendPulse (чат-боти месенджерів).

        Можливості:
        - Отримання повідомлень через Webhook з SendPulse
        - Автоматичне створення/ідентифікація контактів по email
        - Збереження повної історії розмов у картці партнера
        - Підтримка каналів: Telegram, Instagram, Facebook, Viber, Messenger, WhatsApp, LiveChat
        - Черга нових (неідентифікованих) чатів
        - Відповідь клієнту прямо з Odoo Discuss
        - Прикріплення файлів/фото
    """,
    'author': 'Volodymyr Shevchenko',
    'website': 'https://github.com/VladSh77/odoo-chatwoot-connector',
    'license': 'LGPL-3',
    'category': 'Discuss',
    'depends': [
        'mail',
        'contacts',
        'crm',
        'web',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sendpulse_utm_data.xml',
        'data/sendpulse_data.xml',
        'data/clean_data_cron.xml',
        'views/res_config_settings_views.xml',
        'views/sendpulse_connect_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
