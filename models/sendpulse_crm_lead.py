import logging

from markupsafe import Markup, escape
from odoo import models

_logger = logging.getLogger(__name__)


class SendpulseConnectCrmLead(models.Model):
    _inherit = 'sendpulse.connect'

    # ── Magic-number константи (аудит 19.07.2026, issue #8) ───────────────
    _LEAD_MESSAGE_PREVIEW_LEN = 200  # обрізка тексту повідомлення в description ліда

    # ── V2 F4: Auto-create CRM leads ─────────────────────────────────────
    def _auto_create_crm_lead(self):
        """
        Створює crm.lead з цієї розмови, якщо:
        1. auto_create_lead_enabled=True
        2. sp_lead_id ще порожній
        3. Є мінімум ідентифікатор клієнта (partner або email/phone)

        Ідемпотентний — повторний виклик поверне існуючий лід.
        Повертає crm.lead record (або empty recordset якщо не створено).
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.auto_create_lead_enabled', 'False') != 'True':
            return self.env['crm.lead']
        if self.sp_lead_id:
            return self.sp_lead_id
        # Мінімум: партнер, або email/phone
        has_contact = bool(
            self.partner_id
            or self.unidentified_email
            or self.unidentified_phone
            or self.social_username
        )
        if not has_contact:
            _logger.info(
                'SendPulse Odoo: skip auto_create_lead for connect %s — no contact info',
                self.id,
            )
            return self.env['crm.lead']

        # Sales team: з settings або дефолт
        team_id_raw = ICP.get_param('odoo_chatwoot_connector.auto_create_lead_team_id', '')
        team = False
        if team_id_raw:
            try:
                team = self.env['crm.team'].browse(int(team_id_raw)).exists()
            except (ValueError, TypeError):
                team = False
        if not team:
            team = self.env['crm.team'].search([('company_id', '=', self.env.company.id)], limit=1)

        # Description: останні 5 повідомлень + контекст
        recent_messages = self.message_ids.sorted('date', reverse=True)[:5]
        msg_lines = []
        for m in reversed(list(recent_messages)):
            direction = '👤 Клієнт' if m.direction == 'incoming' else '🧑 Оператор'
            msg_lines.append(
                f'{direction} [{m.date:%Y-%m-%d %H:%M}]: '
                f'{(m.text_message or "")[: self._LEAD_MESSAGE_PREVIEW_LEN]}'
            )
        description_parts = [
            f'Джерело: {self._get_service_label()} через SendPulse',
            f'Бот: {self.bot_name or self.bot_id or "—"}',
            f'SendPulse Contact ID: {self.sendpulse_contact_id or "—"}',
        ]
        if self.social_username:
            description_parts.append(f'Username: {self.social_username}')
        if self.sp_child_name:
            description_parts.append(f"Ім'я дитини: {self.sp_child_name}")
        if self.sp_booking_email:
            description_parts.append(f'Booking email (з бота): {self.sp_booking_email}')
        if msg_lines:
            description_parts.append('')
            description_parts.append('Останні повідомлення:')
            description_parts.extend(msg_lines)
        description = '\n'.join(description_parts)

        # Lead title — короткий, з сервісом + іменем
        lead_name = f'[{self._get_service_label()}] {self.name}'
        if self.sp_comment_category and self.sp_comment_category != 'other':
            lead_name += f' — {self._CATEGORY_LABELS.get(self.sp_comment_category, self.sp_comment_category)}'

        lead_vals = {
            'name': lead_name[:255],
            'type': 'lead',
            'description': description,
            'source_id': self.source_id.id if self.source_id else False,
            'team_id': team.id if team else False,
            # Пул + claim: лід падає БЕЗ відповідального — менеджер «бере собі»
            # з лійки (інакше всі ліди вішались на лідера команди й двоє могли
            # вести одного клієнта). Див. docs/TZ_F4_ENABLE_LEAD.md.
            'user_id': False,
        }
        if self.partner_id:
            lead_vals.update(
                {
                    'partner_id': self.partner_id.id,
                    'contact_name': self.partner_id.name,
                    'email_from': self.partner_id.email or False,
                    'phone': self.partner_id.phone or self.partner_id.mobile or False,
                }
            )
        else:
            lead_vals.update(
                {
                    'contact_name': self.name,
                    'email_from': self.unidentified_email or False,
                    'phone': self.unidentified_phone or False,
                }
            )

        try:
            lead = self.env['crm.lead'].sudo().create(lead_vals)
            self.write(
                {
                    'sp_lead_id': lead.id,
                    'sp_funnel_stage': 'lead_created',
                }
            )
            _logger.info(
                'SendPulse Odoo: auto-created crm.lead %s from connect %s',
                lead.id,
                self.id,
            )
            # Системна нотатка у Discuss-канал
            if self.channel_id:
                self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                    body=Markup(
                        '📇 <b>CRM лід створено автоматично</b>: '
                        '<a href="#action=crm.crm_lead_action_pipeline&id={id}&model=crm.lead">'
                        '#{id} {name}</a>'
                    ).format(id=lead.id, name=escape(lead_name)),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            return lead
        except Exception as e:
            _logger.error('SendPulse Odoo: auto_create_lead failed for connect %s: %s', self.id, e)
            return self.env['crm.lead']
