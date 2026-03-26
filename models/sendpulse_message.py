# -*- coding: utf-8 -*-
import ast
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# Іконки каналів для відображення в UI
SERVICE_ICONS = {
    'telegram': '✈️ Telegram',
    'instagram': '📸 Instagram',
    'facebook': '👍 Facebook',
    'messenger': '💬 Messenger',
    'viber': '📳 Viber',
    'whatsapp': '🟢 WhatsApp',
    'tiktok': '🎵 TikTok',
    'livechat': '🌐 LiveChat',
}

SERVICE_SELECTION = [
    ('telegram', 'Telegram'),
    ('instagram', 'Instagram'),
    ('facebook', 'Facebook'),
    ('messenger', 'Messenger'),
    ('viber', 'Viber'),
    ('whatsapp', 'WhatsApp'),
    ('tiktok', 'TikTok'),
    ('livechat', 'LiveChat'),
]


class SendpulseWebhookData(models.Model):
    """Зберігає сирі дані з webhook SendPulse для подальшої обробки."""
    _name = 'sendpulse.webhook.data'
    _description = 'SendPulse Webhook Raw Data'
    _order = 'create_date desc'

    name = fields.Char(string='Ім\'я контакту', index=True)
    sendpulse_contact_id = fields.Char(string='SendPulse Contact ID', index=True)
    service = fields.Selection(SERVICE_SELECTION, string='Канал')
    event_type = fields.Char(string='Тип події')
    raw_data = fields.Text(string='Raw JSON')
    bot_id = fields.Char(string='Bot ID')
    bot_name = fields.Char(string='Назва бота')

    def clear_old_webhooks(self):
        """Cron: видаляє webhook дані старші за 7 днів."""
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=7)
        old_records = self.search([('create_date', '<', cutoff)])
        if old_records:
            _logger.info('SendPulse Odo: видаляємо %d старих webhook записів', len(old_records))
            old_records.unlink()


class SendpulseMessage(models.Model):
    """Зберігає окремі повідомлення з SendPulse (прив'язані до розмови)."""
    _name = 'sendpulse.message'
    _description = 'SendPulse Message'
    _order = 'date asc'

    name = fields.Char(string='Мітка часу')
    date = fields.Datetime(string='Дата', default=fields.Datetime.now)
    raw_json = fields.Text(string='Raw JSON')
    sendpulse_contact_id = fields.Char(string='SendPulse Contact ID')
    connect_id = fields.Many2one(
        'sendpulse.connect', string='Розмова',
        ondelete='cascade', index=True,
    )
    direction = fields.Selection(
        [('incoming', 'Від клієнта'), ('outgoing', 'Від оператора')],
        string='Напрямок', default='incoming',
    )
    message_type = fields.Selection(
        [('text', 'Текст'), ('image', 'Зображення'), ('file', 'Файл'), ('other', 'Інше')],
        string='Тип', default='text',
    )
    text_message = fields.Text(string='Повідомлення', compute='_compute_text_message', store=True)
    attachment_url = fields.Char(string='URL вкладення')

    @api.depends('raw_json')
    def _compute_text_message(self):
        for rec in self:
            if not rec.raw_json:
                rec.text_message = ''
                continue
            try:
                data = ast.literal_eval(rec.raw_json)
                rec.text_message = data.get('text') or data.get('last_message') or ''
            except Exception:
                rec.text_message = rec.raw_json or ''


class PartnerSendpulseMessage(models.Model):
    """Логує повідомлення у вкладці 'Messaging' картки партнера."""
    _name = 'partner.sendpulse.message'
    _description = 'SendPulse Message in Partner Card'
    _order = 'date desc'

    partner_id = fields.Many2one(
        'res.partner', string='Партнер',
        ondelete='cascade', required=True, index=True,
    )
    author_id = fields.Many2one('res.partner', string='Автор')
    date = fields.Datetime(string='Дата', default=fields.Datetime.now)
    text_message = fields.Html(string='Повідомлення')
    service = fields.Selection(SERVICE_SELECTION, string='Канал')
    direction = fields.Selection(
        [('incoming', 'Від клієнта'), ('outgoing', 'Від оператора')],
        string='Напрямок', default='incoming',
    )
    service_label = fields.Char(
        string='Канал (мітка)', compute='_compute_service_label',
    )

    @api.depends('service')
    def _compute_service_label(self):
        for rec in self:
            rec.service_label = SERVICE_ICONS.get(rec.service, rec.service or '')


class PartnerSendpulseChannel(models.Model):
    """
    Зберігає ВСІ соціальні канали партнера (один запис на кожен канал).
    Якщо клієнт написав з Instagram і Facebook — два окремі записи.
    Відображається в картці партнера як список з клікабельними посиланнями.
    """
    _name = 'partner.sendpulse.channel'
    _description = 'SendPulse Канал партнера'
    _order = 'first_contact_date desc'
    _rec_name = 'display_name_computed'

    partner_id = fields.Many2one(
        'res.partner', string='Партнер',
        ondelete='cascade', required=True, index=True,
    )
    service = fields.Selection(SERVICE_SELECTION, string='Канал', required=True)
    sendpulse_contact_id = fields.Char(
        string='SendPulse Contact ID',
        help='UUID контакту в SendPulse для цього каналу',
    )
    social_username = fields.Char(
        string='Username',
        help='Ім\'я користувача в соцмережі (@username або публічне ім\'я)',
    )
    social_profile_url = fields.Char(
        string='URL профілю',
        help='Пряме посилання на профіль (https://www.facebook.com/...)',
    )
    first_contact_date = fields.Datetime(
        string='Перший контакт', default=fields.Datetime.now,
    )
    last_contact_date = fields.Datetime(
        string='Останній контакт', default=fields.Datetime.now,
    )
    message_count = fields.Integer(string='Повідомлень', default=0)
    source_id = fields.Many2one('utm.source', string='UTM Джерело')

    display_name_computed = fields.Char(
        string='Назва', compute='_compute_display_name_computed', store=True,
    )

    _sql_constraints = [
        ('unique_partner_channel',
         'UNIQUE(partner_id, service, sendpulse_contact_id)',
         'Цей канал вже прив\'язаний до партнера'),
    ]

    @api.depends('service', 'social_username', 'social_profile_url')
    def _compute_display_name_computed(self):
        labels = {
            'telegram': 'Telegram', 'instagram': 'Instagram',
            'facebook': 'Facebook', 'messenger': 'Messenger',
            'viber': 'Viber', 'whatsapp': 'WhatsApp',
            'tiktok': 'TikTok', 'livechat': 'LiveChat',
        }
        for rec in self:
            label = labels.get(rec.service, rec.service or '')
            if rec.social_username:
                rec.display_name_computed = f"{label} (@{rec.social_username})"
            elif rec.social_profile_url:
                rec.display_name_computed = f"{label} ({rec.social_profile_url})"
            else:
                rec.display_name_computed = label
