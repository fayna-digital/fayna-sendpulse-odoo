# -*- coding: utf-8 -*-
{
    'name': 'Fayna SendPulse Odo',
    'version': '17.0.3.1.0',
    'summary': 'Fayna Digital — інтеграція SendPulse з Odoo, переписка з клієнтами прямо в Discuss',
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
    'author': 'Fayna Digital — Volodymyr Shevchenko',
    'website': 'https://fayna.company',
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
        'views/sendpulse_connect_views.xml',
        'views/sendpulse_identify_wizard_views.xml',
        'views/res_partner_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # Патч Thread моделі — додає sendpulseConnectId
            'odoo_chatwoot_connector/static/src/thread_patch.js',
            # OWL компонент панелі
            'odoo_chatwoot_connector/static/src/components/sendpulse_info_panel/sendpulse_info_panel.xml',
            'odoo_chatwoot_connector/static/src/components/sendpulse_info_panel/sendpulse_info_panel.js',
            # Реєстрація дії в threadActionsRegistry
            'odoo_chatwoot_connector/static/src/sendpulse_thread_actions.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
