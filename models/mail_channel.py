# -*- coding: utf-8 -*-
import logging
import re

from odoo import models, fields, api, _
from odoo.tools import plaintext2html, html2plaintext

_logger = logging.getLogger(__name__)

# Шаблони системних повідомлень Odoo Discuss (щоб не відправляти їх в SendPulse)
SYSTEM_MSG_PATTERNS = [
    r'joined the channel',
    r'left the channel',
    r'invited',
    r'приєднав',
    r'покинув',
    r'запросив',
]


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    # Зв'язок з розмовою SendPulse
    sendpulse_connect_id = fields.Many2one(
        'sendpulse.connect', string='SendPulse Розмова',
        ondelete='set null', index=True,
    )

    @classmethod
    def sendpulse_channel_get(cls, env, partner_ids, connect_id, operator_partner_id):
        """
        Створює або повертає існуючий discuss.channel для SendPulse розмови.
        Канал типу 'group' — з'являється у Discuss (дзвіночок) для операторів.
        """
        connect = env['sendpulse.connect'].browse(connect_id)
        channel_name = f"[{connect._get_service_label()}] {connect.name}"

        channel = env['discuss.channel'].create({
            'name': channel_name,
            'channel_type': 'group',
            'sendpulse_connect_id': connect_id,
            'description': connect._get_channel_description(),
        })
        channel.add_members(partner_ids=partner_ids)
        return channel

    def message_post(self, **kwargs):
        """
        Override: якщо оператор відповідає у SendPulse каналі —
        відправляємо повідомлення назад у SendPulse через API.
        """
        msg = super().message_post(**kwargs)

        if not self.sendpulse_connect_id:
            return msg

        connect = self.sendpulse_connect_id

        # Пропускаємо системні повідомлення Odoo
        body_plain = html2plaintext(kwargs.get('body', '') or '')
        if self._is_system_message(body_plain):
            return msg

        # Пропускаємо повідомлення що прийшли від клієнта (incoming)
        # Вони постяться через webhook — щоб уникнути дублювання
        author_id = kwargs.get('author_id')
        if author_id and connect.partner_id and author_id == connect.partner_id.id:
            return msg

        # Отримуємо вкладення
        attachment_url = None
        attachment_ids = kwargs.get('attachment_ids', [])
        if attachment_ids:
            attachment_url = self._get_attachment_url(attachment_ids[0])

        # Відправляємо в SendPulse
        if body_plain.strip() or attachment_url:
            connect.send_message_to_sendpulse(body_plain.strip(), attachment_url=attachment_url)

            # Зберігаємо повідомлення оператора в sendpulse.message
            self.env['sendpulse.message'].create({
                'name': fields.Datetime.now().strftime('%Y-%m-%d %H:%M'),
                'date': fields.Datetime.now(),
                'connect_id': connect.id,
                'sendpulse_contact_id': connect.sendpulse_contact_id,
                'direction': 'outgoing',
                'message_type': 'image' if attachment_url else 'text',
                'text_message': body_plain.strip(),
                'attachment_url': attachment_url or False,
                'raw_json': str({'text': body_plain.strip()}),
            })

            # Зберігаємо у вкладці Messaging картки партнера
            if connect.partner_id:
                self.env['partner.sendpulse.message'].create({
                    'partner_id': connect.partner_id.id,
                    'author_id': self.env.user.partner_id.id,
                    'date': fields.Datetime.now(),
                    'text_message': plaintext2html(body_plain.strip()),
                    'service': connect.service,
                    'direction': 'outgoing',
                })

        return msg

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
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            return f"{base_url}/web/content/{att.id}?access_token={att.access_token}"
        except Exception as e:
            _logger.warning('SendPulse Odo: не вдалося отримати URL вкладення: %s', e)
            return None

    def action_unfollow(self):
        """Override: забороняємо покидати SendPulse канал без закриття розмови."""
        self.ensure_one()
        if self.sendpulse_connect_id:
            connect = self.sendpulse_connect_id
            if connect.stage != 'close':
                from odoo.exceptions import UserError
                raise UserError(_(
                    'Щоб вийти з чату — спочатку закрийте розмову кнопкою "Закрити".'
                ))
            else:
                # Видаляємо юзера з операторів при виході із закритого чату
                connect.user_ids = [(3, self.env.user.id)]
        return super().action_unfollow()
