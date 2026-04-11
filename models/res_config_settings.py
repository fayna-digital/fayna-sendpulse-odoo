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

    # ── SendPulse — Відповіді на коментарі ──────────────────────────────
    sp_comment_autoreply_enabled = fields.Boolean(
        string='Автовідповідь на коментарі FB/IG',
        config_parameter='odoo_chatwoot_connector.sp_comment_autoreply_enabled',
        default=True,
    )
    sp_comment_public_enabled = fields.Boolean(
        string='Публічна відповідь під коментарем',
        config_parameter='odoo_chatwoot_connector.sp_comment_public_enabled',
        default=True,
    )
    sp_comment_private_enabled = fields.Boolean(
        string='Приватне повідомлення (перший коментар)',
        config_parameter='odoo_chatwoot_connector.sp_comment_private_enabled',
        default=True,
    )
    fb_page_access_token = fields.Char(
        string='Facebook Page Access Token',
        help='Безстроковий Page Access Token з Facebook Developer Portal. '
             'Потрібен для публікації відповідей на коментарі та private_replies.',
    )
    fb_page_token_is_set = fields.Boolean(
        compute='_compute_fb_page_token_is_set',
    )
    sp_comment_landing_url = fields.Char(
        string='URL лендінгу (у публічних відповідях)',
        config_parameter='odoo_chatwoot_connector.sp_comment_landing_url',
        default='https://lato2026.campscout.eu',
        help='Підставляється як {landing_url} у шаблони публічних відповідей',
    )
    sp_comment_tg_url = fields.Char(
        string='URL Telegram-каналу',
        config_parameter='odoo_chatwoot_connector.sp_comment_tg_url',
        default='https://t.me/campscouting',
        help='Підставляється як {tg_url} у шаблони публічних відповідей',
    )
    sp_comment_yt_url = fields.Char(
        string='URL YouTube-плейлисту',
        config_parameter='odoo_chatwoot_connector.sp_comment_yt_url',
        default='https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV',
        help='Підставляється як {yt_url} у шаблон приватного повідомлення',
    )
    sp_comment_private_text = fields.Text(
        string='Текст приватного повідомлення',
        config_parameter='odoo_chatwoot_connector.sp_comment_private_text',
        help='Шаблон приватного повідомлення. Доступні змінні: {landing_url}, {tg_url}, {yt_url}. '
             'Залиште порожнім щоб використовувати дефолтний текст.',
    )

    @api.depends('fb_page_access_token')
    def _compute_fb_page_token_is_set(self):
        token = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_chatwoot_connector.fb_page_access_token', ''
        )
        for rec in self:
            rec.fb_page_token_is_set = bool(token)

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
        if self.fb_page_access_token:
            self.env['ir.config_parameter'].sudo().set_param(
                'odoo_chatwoot_connector.fb_page_access_token',
                self.fb_page_access_token,
            )
