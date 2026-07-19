import ast
import logging

from odoo import api, fields, models

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

    name = fields.Char(string="Ім'я контакту", index=True)
    sendpulse_contact_id = fields.Char(string='SendPulse Contact ID', index=True)
    service = fields.Selection(SERVICE_SELECTION, string='Канал')
    event_type = fields.Char(string='Тип події')
    raw_data = fields.Text(string='Raw JSON')
    bot_id = fields.Char(string='Bot ID')
    bot_name = fields.Char(string='Назва бота')

    def clear_old_webhooks(self):
        """Cron: видаляє webhook дані старші за 30 днів.

        Було 7 днів — замало для ретроспективного аудиту (звірка з
        sendpulse.message на предмет втрачених повідомлень можлива лише
        поки тут є сирі дані). 30 днів узгоджено з рештою ретеншенів у
        цьому модулі (retention_message_days у omnichannel_bridge = 180,
        але тут легкі текстові JSON-рядки — дешево тримати довше).
        """
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=30)
        old_records = self.search([('create_date', '<', cutoff)])
        if old_records:
            _logger.info('SendPulse Odoo: видаляємо %d старих webhook записів', len(old_records))
            old_records.unlink()

    @api.model
    def cron_check_message_gap(self):
        """
        Cron: щодня звіряє сирі incoming_message-вебхуки (те, що SendPulse
        РЕАЛЬНО надіслав — сирий audit-лог цієї моделі) із sendpulse.message
        (те, що з цього фактично стало повідомленням у розмові). Розрив тут —
        не гіпотеза, а факт: якщо webhook.data є, а sendpulse.message немає,
        щось під час обробки впало.

        Вікно 2 дні (не все 30) — свіжий сигнал, не архів. Затримка 5 хв
        перед перевіркою — дати ретраям SendPulse і власній обробці домовитись,
        інакше false-positive на щойно прийнятих webhook-ах.

        Виключення: коментарі під Instagram/Facebook постами приходять з
        тим самим event_type='incoming_message', але обробляються ОКРЕМО
        (_process_comment_event, інша модель) — це НЕ втрата, а нормальна
        маршрутизація. Відфільтровано за тими ж ознаками, що й у
        _process_incoming_event.is_comment (channel_data.media.media_product_type
        == 'FEED' або item=comment+verb=add).

        Знайдено інцидентом 19.07.2026: попередня (без цього фільтра, без
        NOT EXISTS-кореляції рядок-в-рядок, з LEFT JOIN + count(*)) чорнова
        перевірка того самого показала роздутий у ~3.5 рази "розрив" через
        join-фанаут — контакт з кількома повідомленнями в одному 2-хвилинному
        вікні множив рядки ДО group by. Урок: цей запит — єдине джерело
        правди для gap-перевірки, не переписувати без NOT EXISTS.
        """
        self.env.cr.execute(
            """
            SELECT wd.id, wd.create_date, wd.service, wd.sendpulse_contact_id, wd.name
            FROM sendpulse_webhook_data wd
            WHERE wd.event_type = 'incoming_message'
              AND wd.create_date >= now() - interval '2 days'
              AND wd.create_date < now() - interval '5 minutes'
              AND wd.raw_data NOT LIKE '%%"media_product_type": "FEED"%%'
              AND wd.raw_data NOT LIKE '%%"item": "comment"%%'
              AND NOT EXISTS (
                  SELECT 1 FROM sendpulse_message sm
                  WHERE sm.sendpulse_contact_id = wd.sendpulse_contact_id
                    AND sm.direction = 'incoming'
                    AND sm.date BETWEEN wd.create_date - interval '2 minutes'
                                     AND wd.create_date + interval '2 minutes'
              )
            ORDER BY wd.create_date
            """
        )
        gaps = self.env.cr.dictfetchall()
        if not gaps:
            return

        _logger.error(
            'SendPulse Odoo: знайдено %d webhook(ів) без відповідного sendpulse.message '
            '(можлива втрата повідомлення) за останні 2 дні: %s',
            len(gaps),
            [(g['create_date'], g['service'], g['name']) for g in gaps],
        )

        # Telegram, не bus.bus: сповіщення в браузері бачить лише той, хто
        # саме зараз дивиться в Odoo Discuss — для алерту про можливу втрату
        # даних потрібен канал, який реально доглядають (той самий бот, що й
        # cron_weekly_telegram_report). No-op якщо telegram_alerts_enabled=False.
        lines = '\n'.join(f'• {g["create_date"]} {g["service"]} — {g["name"]}' for g in gaps[:15])
        more = f'\n... ще {len(gaps) - 15}' if len(gaps) > 15 else ''
        message = (
            f'⚠️ <b>SendPulse: можлива втрата повідомлень</b>\n'
            f'{len(gaps)} webhook(ів) за останні 2 дні без відповідного sendpulse.message.\n'
            f'{lines}{more}\n'
            f'Перевір sendpulse.webhook.data (id: {", ".join(str(g["id"]) for g in gaps)}).'
        )
        self.env['sendpulse.connect']._notify_telegram(message, silent=False)


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
        'sendpulse.connect',
        string='Розмова',
        ondelete='cascade',
        index=True,
    )
    direction = fields.Selection(
        [('incoming', 'Від клієнта'), ('outgoing', 'Від оператора')],
        string='Напрямок',
        default='incoming',
    )
    message_type = fields.Selection(
        [('text', 'Текст'), ('image', 'Зображення'), ('file', 'Файл'), ('other', 'Інше')],
        string='Тип',
        default='text',
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
        'res.partner',
        string='Партнер',
        ondelete='cascade',
        required=True,
        index=True,
    )
    author_id = fields.Many2one('res.partner', string='Автор')
    date = fields.Datetime(string='Дата', default=fields.Datetime.now)
    text_message = fields.Html(string='Повідомлення')
    service = fields.Selection(SERVICE_SELECTION, string='Канал')
    direction = fields.Selection(
        [('incoming', 'Від клієнта'), ('outgoing', 'Від оператора')],
        string='Напрямок',
        default='incoming',
    )
    service_label = fields.Char(
        string='Канал (мітка)',
        compute='_compute_service_label',
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
        'res.partner',
        string='Партнер',
        ondelete='cascade',
        required=True,
        index=True,
    )
    service = fields.Selection(SERVICE_SELECTION, string='Канал', required=True)
    sendpulse_contact_id = fields.Char(
        string='SendPulse Contact ID',
        help='UUID контакту в SendPulse для цього каналу',
    )
    social_username = fields.Char(
        string='Username',
        help="Ім'я користувача в соцмережі (@username або публічне ім'я)",
    )
    social_profile_url = fields.Char(
        string='URL профілю',
        help='Пряме посилання на профіль (https://www.facebook.com/...)',
    )
    first_contact_date = fields.Datetime(
        string='Перший контакт',
        default=fields.Datetime.now,
    )
    last_contact_date = fields.Datetime(
        string='Останній контакт',
        default=fields.Datetime.now,
    )
    message_count = fields.Integer(string='Повідомлень', default=0)
    source_id = fields.Many2one('utm.source', string='UTM Джерело')

    display_name_computed = fields.Char(
        string='Назва',
        compute='_compute_display_name_computed',
        store=True,
    )

    _sql_constraints = [
        (
            'unique_partner_channel',
            'UNIQUE(partner_id, service, sendpulse_contact_id)',
            "Цей канал вже прив'язаний до партнера",
        ),
    ]

    @api.depends('service', 'social_username', 'social_profile_url')
    def _compute_display_name_computed(self):
        labels = {
            'telegram': 'Telegram',
            'instagram': 'Instagram',
            'facebook': 'Facebook',
            'messenger': 'Messenger',
            'viber': 'Viber',
            'whatsapp': 'WhatsApp',
            'tiktok': 'TikTok',
            'livechat': 'LiveChat',
        }
        for rec in self:
            label = labels.get(rec.service, rec.service or '')
            if rec.social_username:
                rec.display_name_computed = f'{label} (@{rec.social_username})'
            elif rec.social_profile_url:
                rec.display_name_computed = f'{label} ({rec.social_profile_url})'
            else:
                rec.display_name_computed = label
