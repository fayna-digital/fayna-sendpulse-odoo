import logging
import re

from odoo import models
from odoo.tools.mail import html2plaintext

_logger = logging.getLogger(__name__)

# Шаблони системних повідомлень Odoo Discuss (щоб не відправляти їх у транспорт)
SYSTEM_MSG_PATTERNS = [
    r'joined the channel',
    r'left the channel',
    r'invited',
    r'приєднав',
    r'покинув',
    r'запросив',
    r'запрошено',
]


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
        # Пошук прив'язки розмови незалежно від прав поточного користувача.
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

        # Внутрішні нотатки (mail.mt_note) — не відправляємо клієнту.
        # Підтип можуть передати рядком (subtype_xmlid) або числовим id (subtype_id).
        if self._is_note_subtype(kwargs):
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

    def _is_note_subtype(self, kwargs):
        """Чи є підтип повідомлення внутрішньою нотаткою mail.mt_note."""
        subtype_xmlid = kwargs.get('subtype_xmlid')
        if subtype_xmlid == 'mail.mt_note':
            return True
        subtype_id = kwargs.get('subtype_id')
        if subtype_id:
            note = self.env.ref('mail.mt_note', raise_if_not_found=False)
            if note and int(subtype_id) == note.id:
                return True
        return False

    def _html_to_text(self, html_body):
        """Конвертує HTML в plain text (локальна реалізація)."""
        return html2plaintext(html_body or '')

    def _is_system_message(self, text):
        """Перевіряє чи є повідомлення системним (join/leave тощо)."""
        text_lower = (text or '').lower()
        for pattern in SYSTEM_MSG_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _get_attachment_url(self, attachment_id):
        """Генерує публічний URL для вкладення."""
        try:
            att = self.env['ir.attachment'].browse(attachment_id)
            if not att:
                return None
            if not att.access_token:
                att.generate_access_token()
            # Системний параметр web.base.url доступний лише з правами адміністратора.
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            return f'{base_url}/web/content/{att.id}?access_token={att.access_token}'
        except Exception as e:
            _logger.warning('Channel Bridge: не вдалося отримати URL вкладення: %s', e)
            return None
