{
    'name': 'Fayna Channel Bridge',
    'version': '17.0.1.0.0',
    'summary': 'Fayna Digital — власний прямий транспорт для чат-каналів Odoo (резерв до SendPulse)',
    'description': """
        Власний транспортний шар для DM-каналів (Telegram, Instagram, Facebook/Messenger,
        Viber, WhatsApp, LiveChat, TikTok). Dual-path: SendPulse залишається основною
        гілкою, власний шлях активується паралельно через штатні webhook/API провайдерів.

        M0 (каркас + Telegram пілот):
        - Модель channel.backend (одна на канал + провайдер)
        - Модель channel.message (журнал + ідемпотентність за provider_message_id)
        - Точка розгалуження транспорту в sendpulse.connect._send_single_message
        - Telegram webhook контролер (/bridge/telegram/webhook/<token>)
        - Cron: healthcheck / retry / switch_check
    """,
    'author': 'Fayna Digital — Volodymyr Shevchenko',
    'website': 'https://fayna.agency',
    'license': 'OPL-1',
    'category': 'Discuss',
    'depends': [
        'odoo_chatwoot_connector',
        'mail',
        'web',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/channel_backend_cron.xml',
        'views/channel_backend_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
