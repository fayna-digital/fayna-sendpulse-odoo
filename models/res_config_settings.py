# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── SendPulse OAuth ─────────────────────────────────────────────────
    sendpulse_client_id = fields.Char(
        string='SendPulse Client ID',
        config_parameter='sendpulse_odo.client_id',
        help='Знайти в SendPulse: Settings → API → Client ID',
    )
    sendpulse_client_secret = fields.Char(
        string='SendPulse Client Secret',
        config_parameter='sendpulse_odo.client_secret',
        help='Знайти в SendPulse: Settings → API → Client Secret',
    )
    sendpulse_webhook_token = fields.Char(
        string='Webhook Secret Token',
        config_parameter='sendpulse_odo.webhook_token',
        help='Довільний секретний рядок для перевірки запитів від SendPulse',
    )

    # ── Webhook URL (тільки для читання — для копіювання) ───────────────
    sendpulse_webhook_url = fields.Char(
        string='Webhook URL (скопіюйте в SendPulse)',
        compute='_compute_webhook_url',
        readonly=True,
    )

    @api.depends('sendpulse_webhook_token')
    def _compute_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            rec.sendpulse_webhook_url = f"{base_url}/sendpulse/webhook"
