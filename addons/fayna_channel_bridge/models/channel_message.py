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
    # Поле `name` ніде не заповнюється, тому display name беремо з `date`
    # (завжди заповнене, має default). Найдешевший безпечний варіант без міграції.
    _rec_name = 'date'

    def init(self):
        """
        Partial unique index: (provider_message_id, service) унікальні для
        вхідних повідомлень. Захищає від дублікатів при повторних webhook-ах.
        """
        super().init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS channel_message_incoming_provider_uniq
            ON channel_message (provider_message_id, service)
            WHERE direction = 'incoming' AND provider_message_id IS NOT NULL
              AND provider_message_id != ''
        """)

    name = fields.Char(string='Timestamp')
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
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
        string='Channel',
        index=True,
    )
    direction = fields.Selection(
        [('incoming', 'From customer'), ('outgoing', 'From operator')],
        string='Direction',
        default='incoming',
    )
    state = fields.Selection(
        [
            ('received', 'Received'),
            ('sent', 'Sent'),
            ('failed', 'Error'),
            ('failed_permanent', 'Error (permanent)'),
        ],
        string='Status',
        default='received',
    )
    provider_message_id = fields.Char(
        string='Provider Message ID',
        index=True,
        help='Message ID at the provider (Telegram update_id / message_id)',
    )
    provider_user_id = fields.Char(
        string='Provider User ID',
        help='User ID at the provider (chat_id for Telegram)',
    )
    text_message = fields.Text(string='Message')
    attachment_url = fields.Char(string='Attachment URL')
    raw_json = fields.Text(string='Raw JSON')
    retry_count = fields.Integer(string='Retry attempts', default=0)
    next_retry_at = fields.Datetime(
        string='Next attempt',
        index=True,
        help='Time of the next retry attempt (exponential backoff + jitter). '
        'Empty — try on the next cron pass.',
    )
    last_error = fields.Char(string='Last error')
