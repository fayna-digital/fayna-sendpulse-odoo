import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SendpulseConnectDrip(models.Model):
    _inherit = 'sendpulse.connect'

    # ── V2 F2: Drip campaigns ─────────────────────────────────────────────
    # Magic-number пороги (аудит 19.07.2026, issue #8) — три cron-стріми нижче:
    _DRIP_REMINDER_6H_HOURS = 6  # Stream 1: private_sent без відповіді → нагадування
    _DRIP_OPERATOR_ALERT_HOURS = 2  # Stream 2: customer_replied без відповіді оператора
    _DRIP_BOOKING_REMINDER_DAYS = 3  # Stream 3: lead_created без оплати → нагадування про бронь
    _DRIP_MESSAGE_PREVIEW_LEN = 200  # обрізка last_message_preview у Telegram-алерті

    _DRIP_STOP_KEYWORDS = (
        'stop',
        'не писати',
        'не надсилати',
        'unsubscribe',
        'відписатись',
        'отпишись',
        'отписаться',
        'зупинись',
    )

    def _check_drip_stop_keyword(self, text):
        """Якщо клієнт написав STOP-like — ставимо drip_stop_requested=True."""
        self.ensure_one()
        if not text or self.drip_stop_requested:
            return
        lower = text.lower().strip()
        for kw in self._DRIP_STOP_KEYWORDS:
            if kw in lower:
                self.write({'drip_stop_requested': True})
                _logger.info('SendPulse Odoo: drip opt-out set for connect %s', self.id)
                return

    def _can_send_drip_message(self):
        """Перевірки перш ніж шле drip-повідомлення клієнту."""
        self.ensure_one()
        if self.drip_stop_requested:
            return False, 'opt-out'
        if self.stage == 'close':
            return False, 'closed'
        if self.sp_is_comment:
            return False, 'is_comment'
        # Meta 24h window must be open (або не задано, тоді лімітів нема)
        now = fields.Datetime.now()
        if self.sp_messenger_window_expires_at and self.sp_messenger_window_expires_at < now:
            return False, 'window_closed'
        return True, 'ok'

    @api.model
    def cron_drip_followups(self):
        """
        Погодинний cron для drip-кампаній. Обробляє три окремі сценарії
        за `sp_funnel_stage` + часові трешолди.
        Кожна дія гейтнута toggle у Settings (тонке управління).
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.drip_enabled', 'False') != 'True':
            return
        now = fields.Datetime.now()

        # ── Stream 1: private_sent → no reply 6h → reminder клієнту ─────────
        reminder_6h_text = ICP.get_param(
            'odoo_chatwoot_connector.drip_reminder_6h_text',
            'Привіт! 🙂 Ми надсилали вам деталі про табори — чи отримали? '
            'Будемо раді відповісти на будь-які питання 🏕️',
        )
        if ICP.get_param('odoo_chatwoot_connector.drip_reminder_6h_enabled', 'True') == 'True':
            threshold_6h = now - timedelta(hours=self._DRIP_REMINDER_6H_HOURS)
            candidates = self.search(
                [
                    ('sp_funnel_stage', '=', 'private_sent'),
                    ('sp_first_reply_at', '=', False),  # клієнт ще не відповів
                    ('last_message_date', '<', threshold_6h),
                    ('drip_reminder_6h_sent', '=', False),
                    ('drip_stop_requested', '=', False),
                    ('stage', '!=', 'close'),
                    ('sp_is_comment', '=', False),
                ]
            )
            sent_6h = 0
            for rec in candidates:
                ok, reason = rec._can_send_drip_message()
                if not ok:
                    rec.write({'drip_reminder_6h_sent': True})  # mark щоб не повторювати
                    continue
                try:
                    if rec.send_message_to_sendpulse(reminder_6h_text, attachment_url=None):
                        rec.write({'drip_reminder_6h_sent': True})
                        sent_6h += 1
                except Exception as e:
                    _logger.warning('SendPulse Odoo: drip 6h failed for %s: %s', rec.id, e)
            _logger.info('SendPulse Odoo: drip 6h reminder — sent %d', sent_6h)

        # ── Stream 2: customer_replied → оператор silent 2h → Telegram alert ─
        if ICP.get_param('odoo_chatwoot_connector.drip_operator_alert_enabled', 'True') == 'True':
            threshold_2h = now - timedelta(hours=self._DRIP_OPERATOR_ALERT_HOURS)
            # Шукаємо розмови де клієнт написав але оператор НЕ відповів 2h
            stalled = self.search(
                [
                    ('sp_funnel_stage', '=', 'customer_replied'),
                    ('sp_first_inbound_at', '<', threshold_2h),
                    ('sp_first_reply_at', '=', False),  # оператор ще не відповів
                    ('stage', '!=', 'close'),
                    ('sp_is_comment', '=', False),
                ]
            )
            alerted = 0
            for rec in stalled:
                # Не дублюємо — використовуємо sp_window_alert_sent як marker
                # окрема flag не потрібна бо 2h-алерт одноразовий на розмову
                if rec.drip_followup_24h_sent:
                    continue
                try:
                    self._notify_telegram(
                        f'⏱ <b>Клієнт чекає відповідь 2h+</b>\n\n'
                        f'👤 {rec.name} ({rec._get_service_label()})\n'
                        f'💬 Останнє: <i>{(rec.last_message_preview or "")[: self._DRIP_MESSAGE_PREVIEW_LEN]}</i>\n\n'
                        f'Розмова у черзі SendPulse → Нове повідомлення. Прошу підключитись 🙂',
                        silent=False,
                    )
                    rec.write({'drip_followup_24h_sent': True})
                    alerted += 1
                except Exception as e:
                    _logger.warning(
                        'SendPulse Odoo: drip operator alert failed for %s: %s', rec.id, e
                    )
            _logger.info('SendPulse Odoo: drip operator 2h alert — sent %d', alerted)

        # ── Stream 3: lead_created → без оплати 3д → нагадування про бронь ──
        booking_3d_text = ICP.get_param(
            'odoo_chatwoot_connector.drip_booking_3d_text',
            'Доброго дня! 🌟 Нагадуємо про табір, яким ви цікавились. '
            'Місць залишається все менше — якщо готові забронювати, напишіть, '
            'підготуємо договір і рахунок 🏕️',
        )
        if ICP.get_param('odoo_chatwoot_connector.drip_booking_3d_enabled', 'True') == 'True':
            threshold_3d = now - timedelta(days=self._DRIP_BOOKING_REMINDER_DAYS)
            candidates = self.search(
                [
                    ('sp_funnel_stage', '=', 'lead_created'),
                    ('sp_lead_id', '!=', False),
                    ('drip_booking_3d_sent', '=', False),
                    ('drip_stop_requested', '=', False),
                    ('last_message_date', '<', threshold_3d),
                    ('stage', '!=', 'close'),
                ]
            )
            sent_3d = 0
            for rec in candidates:
                # Перевірка — чи лід не закритий won/lost
                if rec.sp_lead_id and rec.sp_lead_id.stage_id.is_won:
                    rec.write({'drip_booking_3d_sent': True})
                    continue
                ok, _reason = rec._can_send_drip_message()
                if not ok:
                    rec.write({'drip_booking_3d_sent': True})
                    continue
                try:
                    if rec.send_message_to_sendpulse(booking_3d_text, attachment_url=None):
                        rec.write({'drip_booking_3d_sent': True})
                        sent_3d += 1
                except Exception as e:
                    _logger.warning('SendPulse Odoo: drip 3d failed for %s: %s', rec.id, e)
            _logger.info('SendPulse Odoo: drip booking 3d — sent %d', sent_3d)
