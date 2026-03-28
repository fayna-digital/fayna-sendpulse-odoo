# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── SendPulse OAuth ─────────────────────────────────────────────────
    sendpulse_client_id = fields.Char(
        string='SendPulse Client ID',
        config_parameter='odoo_chatwoot_connector.client_id',
        help='Знайти в SendPulse: Settings → API → Client ID',
    )
    sendpulse_client_secret = fields.Char(
        string='SendPulse Client Secret',
        help='Залиште порожнім щоб не змінювати поточне значення',
    )
    sendpulse_secret_is_set = fields.Boolean(
        compute='_compute_sendpulse_secret_is_set',
    )
    sendpulse_webhook_token = fields.Char(
        string='Webhook Secret Token',
        config_parameter='odoo_chatwoot_connector.webhook_token',
        help='Довільний секретний рядок для перевірки запитів від SendPulse',
    )

    # ── Webhook URL (тільки для читання — для копіювання) ───────────────
    sendpulse_webhook_url = fields.Char(
        string='Webhook URL (скопіюйте в SendPulse)',
        compute='_compute_webhook_url',
        readonly=True,
    )

    @api.depends('sendpulse_client_secret')
    def _compute_sendpulse_secret_is_set(self):
        secret = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_chatwoot_connector.client_secret', ''
        )
        for rec in self:
            rec.sendpulse_secret_is_set = bool(secret)

    @api.depends('sendpulse_webhook_token')
    def _compute_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            rec.sendpulse_webhook_url = f"{base_url}/sendpulse/webhook"

    def get_values(self):
        # sendpulse_client_secret навмисно не повертається:
        # поле завжди завантажується порожнім (False == False → не dirty).
        # Реальне значення зберігається/читається через set_values / ir.config_parameter.
        return super().get_values()

    def set_values(self):
        super().set_values()
        if self.sendpulse_client_secret:
            self.env['ir.config_parameter'].sudo().set_param(
                'odoo_chatwoot_connector.client_secret',
                self.sendpulse_client_secret,
            )
