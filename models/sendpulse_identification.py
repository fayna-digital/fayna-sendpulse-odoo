import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SendpulseConnectIdentification(models.Model):
    _inherit = 'sendpulse.connect'

    # ── V2 F3: Bot-wizard ідентифікації ───────────────────────────────────
    _EMAIL_REGEX_IDENTIFICATION = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    _ID_ASK_EMAIL_FIRST = (
        'Вітаємо! 👋 Дякуємо що написали. Підкажіть, будь ласка, ваш email — '
        'надішлемо детальну програму таборів і все найцікавіше 🏕️'
    )
    _ID_ASK_EMAIL_RETRY = (
        'Не зовсім зрозумів email 🙈 Можете надіслати у форматі '
        'example@gmail.com? Так я швидко перевірю чи ви вже у нашій базі.'
    )
    _ID_THANKS = (
        "Дякуємо! 🙂 Записали ваш email. Найближчим часом менеджер зв'яжеться з вами з деталями."
    )
    _ID_GAVE_UP = "Добре, передаю розмову менеджеру — він зв'яжеться з вами найближчим часом 🙂"

    def _is_identification_eligible_service(self):
        """Bot-wizard працює тільки там де можна писати клієнту без обмежень."""
        return self.service in ('telegram', 'instagram', 'messenger', 'whatsapp', 'viber')

    def _try_start_identification(self):
        """
        Викликається для brand-new sendpulse.connect коли partner=None.
        Якщо bot_identification_enabled і сервіс підтримує — шле запит email.
        Повертає True якщо запустив flow, False якщо пропустив.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.bot_identification_enabled', 'False') != 'True':
            return False
        if not self._is_identification_eligible_service():
            return False
        if self.sp_is_comment:
            return False
        # Уже ідентифіковано — не чіпаємо
        if self.partner_id or self.unidentified_email:
            return False
        # Шле запит email
        try:
            sent = self.send_message_to_sendpulse(self._ID_ASK_EMAIL_FIRST, attachment_url=None)
            if sent:
                self.write(
                    {
                        'stage': 'identifying',
                        'id_step': 'ask_email',
                        'id_attempts': 1,
                    }
                )
                _logger.info('SendPulse Odoo: started identification for connect %s', self.id)
                return True
        except Exception as e:
            _logger.warning('SendPulse Odoo: id flow start failed for connect %s: %s', self.id, e)
        return False

    def _try_advance_identification(self, inbound_text):
        """
        Викликається для розмов з stage='identifying' на новий inbound.
        Спробувати вилучити email з тексту.
        Повертає True якщо обробили (тоді skip normal flow).
        """
        self.ensure_one()
        if self.stage != 'identifying' or self.id_step not in ('ask_email', 'ask_email_retry'):
            return False
        import re as _re

        m = _re.search(self._EMAIL_REGEX_IDENTIFICATION, inbound_text or '')
        if m:
            email = m.group(0).lower()
            Partner = self.env['res.partner'].sudo()
            partner = Partner.search([('email', '=', email)], limit=1)
            if not partner:
                partner = Partner.create(
                    {
                        'name': self.name,
                        'email': email,
                        'sendpulse_contact_id': self.sendpulse_contact_id,
                    }
                )
            try:
                self.send_message_to_sendpulse(self._ID_THANKS, attachment_url=None)
            except Exception as e:
                _logger.warning('SendPulse Odoo: failed to send ID_THANKS for connect %s: %s', self.id, e)
            self.write(
                {
                    'partner_id': partner.id,
                    'unidentified_email': False,
                    'unidentified_phone': False,
                    'stage': 'new_message',
                    'id_step': 'done',
                }
            )
            _logger.info(
                'SendPulse Odoo: identified connect %s → partner %s (email=%s)',
                self.id,
                partner.id,
                email,
            )
            return True
        # Ні — retry якщо не вичерпали limit
        max_attempts = 3
        try:
            max_attempts = int(
                self.env['ir.config_parameter']
                .sudo()
                .get_param('odoo_chatwoot_connector.bot_identification_max_attempts', '3')
            )
        except (ValueError, TypeError):
            pass
        if self.id_attempts < max_attempts:
            try:
                self.send_message_to_sendpulse(self._ID_ASK_EMAIL_RETRY, attachment_url=None)
            except Exception as e:
                _logger.warning('SendPulse Odoo: failed to send ID_ASK_EMAIL_RETRY for connect %s: %s', self.id, e)
            self.write(
                {
                    'id_step': 'ask_email_retry',
                    'id_attempts': self.id_attempts + 1,
                }
            )
            return True
        # Limit вичерпаний — give up
        try:
            self.send_message_to_sendpulse(self._ID_GAVE_UP, attachment_url=None)
        except Exception as e:
            _logger.warning('SendPulse Odoo: failed to send ID_GAVE_UP for connect %s: %s', self.id, e)
        self.write(
            {
                'stage': 'new_message',  # передаємо оператору
                'id_step': 'gave_up',
            }
        )
        _logger.info(
            'SendPulse Odoo: identification gave up for connect %s after %d attempts',
            self.id,
            self.id_attempts,
        )
        return True
