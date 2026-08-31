{
    'name': 'Fayna Channel Bridge',
    'version': '17.0.1.4.0',
    'summary': 'Fayna Digital — own direct transport for Odoo chat channels',
    'description': """
        Own transport layer for DM channels on Odoo 17. Messages flow directly
        between the provider and Odoo via the providers' native webhook/API —
        no external intermediary.

        Fully working today — Telegram:
        - Connect wizard: enter the bot token from BotFather, the webhook is
          registered automatically (secret_token auth, route
          /bridge/telegram/webhook/<webhook_id> — no bot token in the URL)
        - Inbound messages, replies, retries and healthcheck — verified by a
          live end-to-end test

        Webhook handlers (inbound + HMAC signature check) also exist for
        Messenger, Instagram, WhatsApp, Viber, TikTok and LiveChat. These are
        connected manually by the administrator — OAuth authorization is not
        implemented yet, and the Viber/TikTok/LiveChat signature schemes are
        not confirmed against a third-party implementation.

        Included:
        - channel.backend / channel.conversation / channel.message models
        - Gallery "Connect channels" (channel.provider catalog) with
          preconditions, region and consent gates
        - Operator UI: conversations and message journal with idempotency by
          provider_message_id
        - Secrets are masked in logs (tokens and webhook secrets never leak)
        - Cron: healthcheck / retry / archive
    """,
    'author': 'Fayna Digital — Volodymyr Shevchenko',
    'website': 'https://fayna.agency',
    'license': 'OPL-1',
    'category': 'Discuss',
    'images': ['static/description/banner.png'],
    'price': 49,
    'currency': 'EUR',
    # `web` прибрано: модуль не має ключа `assets` і жодних прямих посилань на
    # web-моделі; `mail` сам залежить від `web`, тому він підтягується транзитивно.
    'depends': [
        'mail',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/channel_backend_cron.xml',
        'data/channel_provider_data.xml',
        'views/channel_message_views.xml',
        'views/channel_conversation_views.xml',
        'views/channel_backend_views.xml',
        'views/channel_provider_views.xml',
        'wizard/channel_connect_wizard_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
}
