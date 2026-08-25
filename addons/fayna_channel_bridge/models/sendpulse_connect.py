import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

TRANSPORT_SELECTION = [
    ('sendpulse', 'SendPulse'),
    ('own', 'Own (власний)'),
    ('auto', 'Auto (fallback)'),
]


class SendpulseConnectBridge(models.Model):
    """
    _inherit sendpulse.connect — точка розгалуження транспорту.

    Додає поле `transport` (sendpulse | own | auto) і розширює
    `_send_single_message` так, щоб при transport='own' відправка
    маршрутизувалась на власний транспорт через channel.backend.
    """

    _inherit = 'sendpulse.connect'

    transport = fields.Selection(
        TRANSPORT_SELECTION,
        string='Транспорт',
        default='sendpulse',
        help='sendpulse = поточний шлях, own = власний транспорт, '
        'auto = спершу SendPulse, при помилці fallback на власний',
    )

    def _get_channel_backend(self):
        """
        Знаходить активний channel.backend для цієї розмови (за service).
        Повертає запис або None.
        """
        self.ensure_one()
        if not self.service:
            return None
        Backend = self.env['channel.backend'].sudo()
        return Backend.search(
            [
                ('service', '=', self.service),
                ('provider', '=', 'direct'),
                ('active', '=', True),
            ],
            limit=1,
        )

    def _send_single_message(self, text, attachment_url=None):
        """
        Override: точка розгаланження транспорту.

        - transport='own'  → відправка через власний channel.backend
        - transport='auto' → спершу SendPulse; при помилці — fallback на власний
        - transport='sendpulse' → поточний шлях (super)
        """
        self.ensure_one()
        backend = self._get_channel_backend()

        # transport='own' — власний транспорт напряму
        if backend and self.transport == 'own':
            return self._send_via_own(backend, text, attachment_url)

        # transport='auto' — спершу SendPulse, при помилці fallback
        if backend and self.transport == 'auto':
            ok = super()._send_single_message(text, attachment_url)
            if ok:
                return True
            _logger.warning(
                'Channel Bridge: SendPulse send failed for connect=%s, fallback to own transport',
                self.id,
            )
            return self._send_via_own(backend, text, attachment_url)

        # transport='sendpulse' (за замовчуванням) — поточний шлях
        return super()._send_single_message(text, attachment_url)

    def _send_via_own(self, backend, text, attachment_url=None):
        """
        Надсилає через власний транспорт і логує у channel.message.
        """
        provider_user_id = self._get_provider_user_id()
        ok, provider_msg_id, err = backend.send_message(
            text,
            attachment_url=attachment_url,
            provider_user_id=provider_user_id,
        )
        # Журнал власного транспорту
        self.env['channel.message'].sudo().create(
            {
                'backend_id': backend.id,
                'service': self.service,
                'direction': 'outgoing',
                'state': 'sent' if ok else 'failed',
                'provider_message_id': provider_msg_id,
                'provider_user_id': provider_user_id,
                'text_message': text,
                'attachment_url': attachment_url or False,
                'last_error': err or '',
            }
        )
        if not ok:
            _logger.error(
                'Channel Bridge: own transport send failed for connect=%s — %s',
                self.id,
                err,
            )
        return ok

    def _get_provider_user_id(self):
        """
        Повертає provider_user_id для цієї розмови.

        Для власного шляху sendpulse_contact_id має формат
        `own:{service}:{provider_user_id}` (див. ТЗ §8) — парсимо звідси.
        Для поточних SendPulse-розмов — fallback на сам sendpulse_contact_id.
        """
        self.ensure_one()
        cid = self.sendpulse_contact_id or ''
        if cid.startswith('own:'):
            parts = cid.split(':')
            if len(parts) >= 3:
                return ':'.join(parts[2:])
        return cid
