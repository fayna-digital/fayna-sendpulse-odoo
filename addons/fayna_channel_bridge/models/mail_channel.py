import logging

from odoo import models
from odoo.tools.mail import html2plaintext

_logger = logging.getLogger(__name__)


class DiscussChannelBridge(models.Model):
    """
    _inherit discuss.channel — маршрутизація вихідних повідомлень.

    Коли оператор відповідає в Discuss-каналі, що прив'язаний до
    channel.conversation — відправка йде через власний транспорт
    (channel.backend) замість зовнішнього провайдера.
    """

    _inherit = 'discuss.channel'

    def _get_bridge_conversation(self):
        """Повертає channel.conversation, прив'язану до цього Discuss-каналу."""
        self.ensure_one()
        return (
            self.env['channel.conversation'].sudo().search([('channel_id', '=', self.id)], limit=1)
        )

    def message_post(self, **kwargs):
        """
        Override: якщо Discuss-канал прив'язаний до channel.conversation —
        відправляємо повідомлення через власний транспорт.
        Інакше — поточний шлях (super).
        """
        conversation = self._get_bridge_conversation()
        if not conversation:
            return super().message_post(**kwargs)

        # Пропускаємо вхідні (webhook) повідомлення — не відправляємо назад
        if self.env.context.get('bridge_incoming'):
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
            conversation._send_single_message(body_plain.strip(), attachment_url=attachment_url)
            if conversation.stage == 'new_message':
                conversation.write({'stage': 'in_progress'})

        return msg

    def _html_to_text(self, html_body):
        """Конвертує HTML в plain text (локальна реалізація)."""
        return html2plaintext(html_body or '')
