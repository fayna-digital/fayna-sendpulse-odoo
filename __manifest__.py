{
    'name': 'Odoo Chatwoot Connector',
    'version': '17.0.1.0.0',
    'summary': 'Two-way integration between Odoo and Chatwoot',
    'description': """
        Integrate Chatwoot with Odoo CRM.
        - Receive messages via Webhook
        - Create Leads/Contacts automatically
        - Sync conversation history
    """,
    'author': 'Volodymyr Shevchenko',
    'website': 'https://github.com/VladSh77/odoo-chatwoot-connector',
    'license': 'LGPL-3',
    'category': 'Sales/CRM',
    'depends': [
        'base',
        'crm',
        'web',
    ],
    'data': [
        # 'security/ir.model.access.csv',
        # 'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
