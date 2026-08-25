import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ChannelMessage(models.Model):
    """
    Журнал повідомлень власного транспорту.

    Ідемпотентність: унікальний partial index на
    (provider_message_id, service, direction='incoming') — повторний webhook
    від провайдера не дублює повідомлення.
    """

    _name = 'channel.message'
    _description = 'Channel Bridge Message'
    _order = 'date asc'

    def init(self):
        """
        Partial unique index: (provider_message_id, service) унікальні для
        вхідних повідомлень — аналог існуючого partial unique index у
        sendpulse.connect. Захищає від дублікатів при повторних webhook-ах.
        """
        super().init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS channel_message_incoming_provider_uniq
            ON channel_message (provider_message_id, service)
            WHERE direction = 'incoming' AND provider_message_id IS NOT NULL
              AND provider_message_id != ''
        """)

    name = fields.Char(string='Мітка часу')
    date = fields.Datetime(string='Дата', default=fields.Datetime.now)
    backend_id = fields.Many2one(
        'channel.backend',
        string='Backend',
        ondelete='cascade',
        index=True,
    )
    service = fields.Selection(
        [
            ('telegram', 'Telegram'),
            ('instagram', 'Instagram'),
            ('facebook', 'Facebook'),
            ('messenger', 'Messenger'),
            ('viber', 'Viber'),
            ('whatsapp', 'WhatsApp'),
            ('tiktok', 'TikTok'),
            ('livechat', 'LiveChat'),
        ],
        string='Канал',
        index=True,
    )
    direction = fields.Selection(
        [('incoming', 'Від клієнта'), ('outgoing', 'Від оператора')],
        string='Напрямок',
        default='incoming',
    )
    state = fields.Selection(
        [
            ('received', 'Отримано'),
            ('sent', 'Надіслано'),
            ('failed', 'Помилка'),
        ],
        string='Стан',
        default='received',
    )
    provider_message_id = fields.Char(
        string='Provider Message ID',
        index=True,
        help='ID повідомлення у провайдера (Telegram update_id / message_id)',
    )
    provider_user_id = fields.Char(
        string='Provider User ID',
        help='ID користувача у провайдера (chat_id для Telegram)',
    )
    text_message = fields.Text(string='Повідомлення')
    attachment_url = fields.Char(string='URL вкладення')
    raw_json = fields.Text(string='Raw JSON')
    retry_count = fields.Integer(string='Спроби повтору', default=0)
    last_error = fields.Char(string='Остання помилка')
