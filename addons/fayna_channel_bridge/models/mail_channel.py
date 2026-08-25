import logging

from odoo import fields, models
from odoo.tools import plaintext2html

_logger = logging.getLogger(__name__)


class DiscussChannelBridge(models.Model):
    """
    _inherit discuss.channel — маршрутизація вихідних повідомлень.

    Коли оператор відповідає в Discuss-каналі, що прив'язаний до
    sendpulse.connect з transport='own' — відправка йде через власний
    транспорт (channel.backend) замість SendPulse.
    """

    _inherit = 'discuss.channel'

    def message_post(self, **kwargs):
        """
        Override: якщо розмова має transport='own' — відправляємо через
        власний транспорт. Інакше — поточний шлях (super).
        """
        if not self.sendpulse_connect_id:
            return super().message_post(**kwargs)

        connect = self.sendpulse_connect_id
        if connect.transport != 'own':
            return super().message_post(**kwargs)

        # Пропускаємо вхідні (webhook) повідомлення — не відправляємо назад
        if self.env.context.get('sendpulse_incoming'):
            return super().message_post(**kwargs)

        # Системні нотифікації Odoo — не відправляємо
        if kwargs.get('message_type') in ('notification', 'auto_comment'):
            return super().message_post(**kwargs)

        # Спершу постимо в канал (щоб оператор бачив), потім відправляємо
        msg = super().message_post(**kwargs)

        body_plain = self._html_to_text(kwargs.get('body', '') or '')
        if self._is_system_message(body_plain):
            return msg

        attachment_url = None
        attachment_ids = kwargs.get('attachment_ids', [])
        if attachment_ids:
            attachment_url = self._get_attachment_url(attachment_ids[0])

        if body_plain.strip() or attachment_url:
            connect._send_single_message(body_plain.strip(), attachment_url=attachment_url)
            if connect.stage == 'new_message':
                connect.write({'stage': 'in_progress'})

            # Зберігаємо повідомлення оператора в sendpulse.message
            now = fields.Datetime.now()
            self.env['sendpulse.message'].create(
                {
                    'name': now.strftime('%Y-%m-%d %H:%M'),
                    'date': now,
                    'connect_id': connect.id,
                    'sendpulse_contact_id': connect.sendpulse_contact_id,
                    'direction': 'outgoing',
                    'message_type': 'image' if attachment_url else 'text',
                    'text_message': body_plain.strip(),
                    'attachment_url': attachment_url or False,
                    'raw_json': str({'text': body_plain.strip()}),
                }
            )

            # Зберігаємо у вкладці Messaging картки партнера
            if connect.partner_id:
                self.env['partner.sendpulse.message'].create(
                    {
                        'partner_id': connect.partner_id.id,
                        'author_id': self.env.user.partner_id.id,
                        'date': now,
                        'text_message': plaintext2html(body_plain.strip()),
                        'service': connect.service,
                        'direction': 'outgoing',
                    }
                )

        return msg

    def _html_to_text(self, html_body):
        """Конвертує HTML в plain text (аналог mail_channel.py)."""
        from odoo_chatwoot_connector.models.mail_channel import _html_to_text

        return _html_to_text(html_body)
