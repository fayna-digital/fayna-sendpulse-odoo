import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SendpulseConnectRodo(models.Model):
    _inherit = 'sendpulse.connect'

    # ── V2 F13b: RODO unsubscribe detection ───────────────────────────────
    # Ключові фрази де клієнт просить НЕ надсилати більше маркетингові матеріали.
    # Мультимовно: UK + PL + RU + EN. Case-insensitive, whole-word.
    UNSUBSCRIBE_PATTERNS = (
        r'\bstop\b',
        r'\bunsubscribe\b',
        r'\bвідпис',  # відписатися, відпис
        r'\bотпис',  # отписаться, отпис
        r'\bне\s+над[іи]слайте',
        r'\bне\s+пиш[іи]ть',
        r'\bnie\s+chc[ęe]',  # nie chcę / nie chce
        r'\bwypisz\b',  # wypiszcie / wypisać
        r'\brezygnuj',  # rezygnuję
        r'\busuńcie\s+mnie',
        r'\bвидаліть\s+мене',
        r'\bудалите\s+меня',
    )

    def _check_and_record_unsubscribe(self, text, message):
        """
        Сканує текст клієнта на unsubscribe-фрази (STOP, відписка, nie chcę, ...).
        Якщо знайдено — фіксує withdrawal для всіх активних lead-magnet purposes
        цього connect (email + SMS). Майбутні send-и пропустяться.
        """
        if not text:
            return False
        import re

        lower = text.lower()
        matched = None
        for pat in self.UNSUBSCRIBE_PATTERNS:
            if re.search(pat, lower, re.IGNORECASE | re.UNICODE):
                matched = pat
                break
        if not matched:
            return False
        ConsentLog = self.env['sendpulse.privacy.consent.log'].sudo()
        email = (
            (self.sp_booking_email or (self.partner_id.email if self.partner_id else '') or '')
            .strip()
            .lower()
        )
        phone = ((self.partner_id.mobile or self.partner_id.phone) if self.partner_id else '') or ''
        phone = phone.strip()
        recorded = []
        # Email withdrawal
        if email:
            ConsentLog.record_consent(
                purpose='lead_magnet_email',
                channel='email',
                partner_id=self.partner_id.id if self.partner_id else False,
                connect_id=self.id,
                message_id=message.id if message else False,
                email=email,
                consent_given=False,
                exact_response=text[:500],
                notes=f'Auto-recorded unsubscribe (pattern: {matched})',
            )
            recorded.append('email')
        # SMS withdrawal
        if phone:
            ConsentLog.record_consent(
                purpose='lead_magnet_sms',
                channel='sms',
                partner_id=self.partner_id.id if self.partner_id else False,
                connect_id=self.id,
                message_id=message.id if message else False,
                phone=phone,
                consent_given=False,
                exact_response=text[:500],
                notes=f'Auto-recorded unsubscribe (pattern: {matched})',
            )
            recorded.append('sms')
        # Messenger withdrawal (на випадок майбутніх marketing-повідомлень у чат)
        if self.partner_id or self.sendpulse_contact_id:
            ConsentLog.record_consent(
                purpose='marketing_email',  # умовно — позначка «більше не писати»
                channel='messenger',
                partner_id=self.partner_id.id if self.partner_id else False,
                connect_id=self.id,
                message_id=message.id if message else False,
                consent_given=False,
                exact_response=text[:500],
                notes=f'Auto-recorded unsubscribe via messenger (pattern: {matched})',
            )
            recorded.append('messenger')
        _logger.info(
            'SendPulse Odoo: RODO unsubscribe detected у connect %s — записав withdrawals: %s (pattern: %s)',
            self.id,
            recorded,
            matched,
        )
        return True
