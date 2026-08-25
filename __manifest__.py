{
    'name': 'Fayna SendPulse Odoo',
    'version': '17.0.1.15.14',
    'summary': 'Fayna Digital — SendPulse + AI-помічник + lead magnet (PDF/SMS) + live event seats + drip + A/B шаблони + multi-page FB/IG',
    'description': """
        AI-first omnichannel рішення від Fayna Digital на базі Odoo 17.

        Core:
        - Двостороння інтеграція SendPulse ↔ Odoo Discuss
        - Канали: Telegram, Instagram, Facebook/Messenger, Viber, WhatsApp, LiveChat, TikTok
        - Автоматична ідентифікація контактів (email / phone / bot-vars)
        - Черга нових чатів, повна історія у картці партнера, UTM-атрибуція

        AI + Automation (v2):
        - AI-драфти відповіді оператору (Claude Haiku у sidebar Discuss)
        - Авто-переклад UA ↔ PL
        - FAQ RAG-відповідач (confidence-based auto-send)
        - Lead magnet: email → брендований PDF-лист + SMS → промокод з loyalty.program
        - Live event seats awareness (FOMO <30%, чесна відмова коли повний)
        - Drip-нагадування 6h/24h
        - A/B публічні шаблони (epsilon-greedy + conversion tracking)
        - Multi-page Facebook/Instagram (через System User, Meta App Review approved)
        - Meta Graph API v25.0 + LLM-класифікатор коментарів

        Reliability:
        - PostgreSQL advisory lock + partial unique index (race-safe)
        - Backfill missed-inbound з contact.last_message
        - Weekly FB Page Token check + Telegram alerts
    """,
    'author': 'Fayna Digital — Volodymyr Shevchenko',
    'website': 'https://fayna.agency',
    'license': 'OPL-1',
    'category': 'Discuss',
    'depends': [
        'mail',
        'contacts',
        'crm',
        'web',
        'loyalty',
        'sms',
        'sale',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sendpulse_utm_data.xml',
        'data/sendpulse_data.xml',
        'data/sendpulse_faq_seed.xml',
        'data/sendpulse_public_templates_seed.xml',
        'data/mail_template_lead_magnet.xml',
        'data/mail_template_offer_pl.xml',
        'data/clean_data_cron.xml',
        'data/lead_autocreate_config.xml',
        'views/sendpulse_connect_views.xml',
        'views/sendpulse_identify_wizard_views.xml',
        'views/meta_profile_views.xml',
        'views/sendpulse_facebook_page_views.xml',
        'views/sendpulse_faq_entry_views.xml',
        'views/sendpulse_public_template_views.xml',
        'views/sendpulse_privacy_consent_log_views.xml',
        'views/res_partner_views.xml',
        'wizards/oboz300_quick_send_views.xml',
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
