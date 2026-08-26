{
    "name": "Fayna Channel Bridge",
    "version": "17.0.1.0.0",
    "summary": "Fayna Digital — власний прямий транспорт для чат-каналів Odoo",
    "description": """
        Власний транспортний шар для DM-каналів (Telegram, Instagram, Facebook/Messenger,
        Viber, WhatsApp, LiveChat, TikTok). Повністю автономний — без зовнішнього
        посередника, через штатні webhook/API провайдерів.

        - Модель channel.backend (одна на канал + провайдер)
        - Модель channel.conversation (розмови, автономна)
        - Модель channel.message (журнал + ідемпотентність за provider_message_id)
        - Telegram webhook контролер (/bridge/telegram/webhook/<token>)
        - Cron: healthcheck / retry / archive
    """,
    "author": "Fayna Digital — Volodymyr Shevchenko",
    "website": "https://fayna.agency",
    "license": "OPL-1",
    "category": "Discuss",
    "depends": [
        "mail",
        "web",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/channel_backend_cron.xml",
        "views/channel_backend_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
