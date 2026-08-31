{
    "name": "Fayna Channel Bridge",
    "version": "17.0.1.4.0",
    "summary": "Fayna Digital — own direct transport for Odoo chat channels",
    "description": """
        Own transport layer for DM channels (Telegram, Instagram, Facebook/Messenger,
        Viber, WhatsApp, LiveChat, TikTok). Fully autonomous — no external
        intermediary, via the providers' native webhook/API.

        - channel.backend model (one per channel + provider)
        - channel.conversation model (conversations, autonomous)
        - channel.message model (journal + idempotency by provider_message_id)
        - Telegram webhook controller (/bridge/telegram/webhook/<token>)
        - Cron: healthcheck / retry / archive
    """,
    "author": "Fayna Digital — Volodymyr Shevchenko",
    "website": "https://fayna.agency",
    "license": "OPL-1",
    "category": "Discuss",
    "images": ["static/description/banner.png"],
    "price": 49,
    "currency": "EUR",
    # `web` прибрано: модуль не має ключа `assets` і жодних прямих посилань на
    # web-моделі; `mail` сам залежить від `web`, тому він підтягується транзитивно.
    "depends": [
        "mail",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/channel_backend_cron.xml",
        "data/channel_provider_data.xml",
        "views/channel_message_views.xml",
        "views/channel_conversation_views.xml",
        "views/channel_backend_views.xml",
        "views/channel_provider_views.xml",
        "wizard/channel_connect_wizard_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
    "auto_install": False,
}
