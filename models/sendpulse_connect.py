# -*- coding: utf-8 -*-
import logging
import requests
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import plaintext2html

_logger = logging.getLogger(__name__)

UTM_SOURCE_MAP = {
    'telegram': 'odoo_chatwoot_connector.utm_source_telegram',
    'instagram': 'odoo_chatwoot_connector.utm_source_instagram',
    'facebook': 'odoo_chatwoot_connector.utm_source_facebook',
    'messenger': 'odoo_chatwoot_connector.utm_source_messenger',
    'viber': 'odoo_chatwoot_connector.utm_source_viber',
    'whatsapp': 'odoo_chatwoot_connector.utm_source_whatsapp',
    'tiktok': 'odoo_chatwoot_connector.utm_source_tiktok',
    'livechat': 'odoo_chatwoot_connector.utm_source_livechat',
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

STAGE_SELECTION = [
    ('new', 'Новий'),
    ('in_progress', 'В роботі'),
    ('new_message', 'Нове повідомлення'),
    ('close', 'Закрито'),
]


class SendpulseConnect(models.Model):
    """
    Центральна модель розмови SendPulse.
    Кожна розмова = один запис тут + один discuss.channel в Odoo.
    """
    _name = 'sendpulse.connect'
    _description = 'SendPulse Розмова'
    _order = 'write_date desc'

    # ── Основні поля ────────────────────────────────────────────────────
    name = fields.Char(string='Ім\'я контакту', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner', string='Клієнт', index=True, ondelete='set null',
        help='Порожньо = контакт ще не ідентифікований',
    )
    stage = fields.Selection(STAGE_SELECTION, string='Статус', default='new', index=True)
    service = fields.Selection(SERVICE_SELECTION, string='Канал', index=True)

    # ── Дані з SendPulse ────────────────────────────────────────────────
    sendpulse_contact_id = fields.Char(
        string='SendPulse Contact ID', index=True,
        help='UUID контакту в SendPulse — головний ключ ідентифікації',
    )
    bot_id = fields.Char(string='Bot ID')
    bot_name = fields.Char(string='Бот')
    last_message_preview = fields.Char(string='Останнє повідомлення')
    last_message_date = fields.Datetime(string='Дата останнього повідомлення')

    # ── Ідентифікаційні дані соцмереж ───────────────────────────────────
    social_username = fields.Char(
        string='Username / Профіль',
        help='Ім\'я користувача або посилання на профіль у соцмережах',
    )
    social_profile_url = fields.Char(
        string='URL профілю',
        help='Пряме посилання на профіль (для Facebook, Instagram тощо)',
    )
    unidentified_email = fields.Char(
        string='Email (з SendPulse)',
        help='Email отриманий від SendPulse до ідентифікації партнера',
    )
    unidentified_phone = fields.Char(string='Телефон (з SendPulse)')

    # ── Odoo Discuss ────────────────────────────────────────────────────
    channel_id = fields.Many2one(
        'discuss.channel', string='Discuss Канал',
        ondelete='set null',
    )
    user_ids = fields.Many2many(
        'res.users', string='Оператори',
        help='Оператори, призначені на цю розмову',
    )

    # ── Повідомлення ────────────────────────────────────────────────────
    message_ids = fields.One2many(
        'sendpulse.message', 'connect_id', string='Повідомлення',
    )
    message_count = fields.Integer(
        string='Кількість повідомлень', compute='_compute_message_count',
    )

    # ── Допоміжні ───────────────────────────────────────────────────────
    last_notified_at = fields.Datetime(string='Остання сповіщення')
    source_id = fields.Many2one('utm.source', string='UTM Джерело')

    # ── Computed ────────────────────────────────────────────────────────
    is_unidentified = fields.Boolean(
        string='Не ідентифікований', compute='_compute_is_unidentified', store=True,
    )
    service_icon = fields.Char(
        string='Іконка каналу', compute='_compute_service_icon',
    )

    @api.depends('partner_id')
    def _compute_is_unidentified(self):
        for rec in self:
            rec.is_unidentified = not bool(rec.partner_id)

    @api.depends('service')
    def _compute_service_icon(self):
        icons = {
            'telegram': '✈️', 'instagram': '📸', 'facebook': '👍',
            'messenger': '💬', 'viber': '📳', 'whatsapp': '🟢',
            'tiktok': '🎵', 'livechat': '🌐',
        }
        for rec in self:
            rec.service_icon = icons.get(rec.service, '💬')

    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    # ════════════════════════════════════════════════════════════════════
    # ORM Overrides
    # ════════════════════════════════════════════════════════════════════

    def create(self, vals):
        rec = super().create(vals)
        # Сповіщаємо операторів про нову розмову
        rec._notify_operators_new_conversation()
        return rec

    def write(self, vals):
        result = super().write(vals)
        if 'stage' in vals and vals['stage'] == 'new_message':
            for rec in self:
                rec._notify_operators_new_message()
        return result

    def unlink(self):
        for rec in self:
            rec._close_channel()
        return super().unlink()

    # ════════════════════════════════════════════════════════════════════
    # Основні методи
    # ════════════════════════════════════════════════════════════════════

    def action_open_discuss(self):
        """Відкриває Odoo Discuss для цієї розмови."""
        self.ensure_one()
        if not self.channel_id:
            self._create_discuss_channel()
        if not self.channel_id:
            raise UserError(_('Не вдалося відкрити чат. Спробуйте ще раз.'))

        # Перевіряємо чи поточний юзер є учасником
        member = self.env['discuss.channel.member'].search([
            ('channel_id', '=', self.channel_id.id),
            ('partner_id', '=', self.env.user.partner_id.id),
        ], limit=1)
        if not member:
            self.channel_id.add_members(partner_ids=[self.env.user.partner_id.id])

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'discuss.channel',
            'res_id': self.channel_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_identify_partner(self):
        """Відкриває wizard для прив'язки неідентифікованого чату до партнера."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ідентифікувати клієнта'),
            'res_model': 'sendpulse.connect',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'identify_mode': True},
        }

    def action_close(self):
        """Закриває розмову."""
        self.ensure_one()
        self.write({'stage': 'close'})
        if self.partner_id:
            self._post_history_to_partner()

    def action_reopen(self):
        """Повторно відкриває закриту розмову."""
        self.ensure_one()
        self.write({'stage': 'in_progress'})

    def _create_discuss_channel(self):
        """
        Створює discuss.channel для розмови.
        Канал з'являється у Discuss (дзвіночок) для призначених операторів.
        """
        self.ensure_one()
        channel_name = f"[{self._get_service_label()}] {self.name}"

        channel = self.env['discuss.channel'].create({
            'name': channel_name,
            'channel_type': 'group',
            'sendpulse_connect_id': self.id,
            'description': self._get_channel_description(),
        })

        # Додаємо поточного юзера + призначених операторів
        partner_ids = [self.env.user.partner_id.id]
        for user in self.user_ids:
            if user.partner_id.id not in partner_ids:
                partner_ids.append(user.partner_id.id)

        channel.add_members(partner_ids=partner_ids)

        # Якщо є збережені повідомлення — постимо їх в канал
        for msg in self.message_ids.sorted('date'):
            direction_label = '👤 Клієнт' if msg.direction == 'incoming' else '🧑‍💼 Оператор'
            body = f"<b>{direction_label}</b> [{msg.name}]:<br/>{plaintext2html(msg.text_message or '')}"
            if msg.attachment_url:
                body += f'<br/><a href="{msg.attachment_url}" target="_blank">📎 Вкладення</a>'
            channel.message_post(
                body=body,
                author_id=self.partner_id.id if msg.direction == 'outgoing' and self.partner_id else None,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

        self.write({
            'channel_id': channel.id,
            'stage': 'in_progress',
        })
        return channel

    def _get_service_label(self):
        labels = {
            'telegram': 'TG', 'instagram': 'IG', 'facebook': 'FB',
            'messenger': 'MSG', 'viber': 'VB', 'whatsapp': 'WA',
            'tiktok': 'TT', 'livechat': 'LC',
        }
        return labels.get(self.service, self.service or '?')

    def _get_channel_description(self):
        parts = [f"SendPulse | {self.service or '?'}"]
        if self.social_username:
            parts.append(f"@{self.social_username}")
        if self.social_profile_url:
            parts.append(self.social_profile_url)
        if self.unidentified_email:
            parts.append(self.unidentified_email)
        return ' | '.join(parts)

    def _close_channel(self):
        """Архівує discuss.channel при закритті розмови."""
        if self.channel_id:
            self.channel_id.write({'active': False})

    def _post_history_to_partner(self):
        """Зберігає всі повідомлення у вкладці Messaging картки партнера."""
        self.ensure_one()
        if not self.partner_id:
            return
        for msg in self.message_ids.sorted('date'):
            self.env['partner.sendpulse.message'].create({
                'partner_id': self.partner_id.id,
                'date': msg.date,
                'text_message': plaintext2html(msg.text_message or ''),
                'service': self.service,
                'direction': msg.direction,
            })

    def assign_partner(self, partner_id):
        """
        Прив'язує ідентифікованого партнера до розмови.
        Переносить усю історію в його картку.
        """
        self.ensure_one()
        self.write({'partner_id': partner_id})
        self._post_history_to_partner()
        # Оновлюємо UTM джерело у партнера
        self._update_partner_source()
        # Оновлюємо назву каналу
        if self.channel_id:
            partner = self.env['res.partner'].browse(partner_id)
            self.channel_id.write({
                'name': f"[{self._get_service_label()}] {partner.name}",
            })

    def _update_partner_source(self):
        """
        Додає або оновлює запис у partner.sendpulse.channel для партнера.
        Якщо клієнт написав з кількох каналів — кожен зберігається окремо.
        """
        if not self.partner_id or not self.service:
            return

        # Знаходимо UTM джерело
        source_id = False
        utm_xml_id = UTM_SOURCE_MAP.get(self.service)
        if utm_xml_id:
            try:
                source_id = self.env.ref(utm_xml_id).id
            except Exception:
                pass

        # Шукаємо чи вже є запис для цього каналу у цього партнера
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('service', '=', self.service),
        ]
        if self.sendpulse_contact_id:
            domain.append(('sendpulse_contact_id', '=', self.sendpulse_contact_id))

        existing = self.env['partner.sendpulse.channel'].search(domain, limit=1)

        if existing:
            # Оновлюємо дату останнього контакту і лічильник
            update_vals = {'last_contact_date': fields.Datetime.now()}
            if self.social_username and not existing.social_username:
                update_vals['social_username'] = self.social_username
            if self.social_profile_url and not existing.social_profile_url:
                update_vals['social_profile_url'] = self.social_profile_url
            existing.write(update_vals)
            existing._cr.execute(
                "UPDATE partner_sendpulse_channel SET message_count = message_count + 1 WHERE id = %s",
                (existing.id,)
            )
        else:
            # Новий канал для цього партнера — створюємо запис
            self.env['partner.sendpulse.channel'].create({
                'partner_id': self.partner_id.id,
                'service': self.service,
                'sendpulse_contact_id': self.sendpulse_contact_id or False,
                'social_username': self.social_username or False,
                'social_profile_url': self.social_profile_url or False,
                'source_id': source_id or False,
                'first_contact_date': fields.Datetime.now(),
                'last_contact_date': fields.Datetime.now(),
                'message_count': 1,
            })

    # ════════════════════════════════════════════════════════════════════
    # Сповіщення
    # ════════════════════════════════════════════════════════════════════

    def _notify_operators_new_conversation(self):
        """Сповіщає операторів про нову розмову через Odoo Discuss."""
        group = self.env.ref('odoo_chatwoot_connector.group_sendpulse_officer', raise_if_not_found=False)
        if not group:
            return
        partner_ids = group.users.mapped('partner_id').ids
        if partner_ids:
            self.env['bus.bus']._sendmany([
                (partner_id, 'simple_notification', {
                    'title': _('SendPulse: Нова розмова'),
                    'message': f"{self.service_icon} {self.name}: нова розмова з {self.service or 'SendPulse'}",
                    'sticky': False,
                })
                for partner_id in partner_ids
            ])

    def _notify_operators_new_message(self):
        """Сповіщає операторів про нове повідомлення (throttle: 1/год)."""
        now = datetime.now()
        if self.last_notified_at and (now - self.last_notified_at) < timedelta(hours=1):
            return
        self.write({'last_notified_at': now})
        target_partners = []
        if self.user_ids:
            target_partners = self.user_ids.mapped('partner_id').ids
        else:
            group = self.env.ref('odoo_chatwoot_connector.group_sendpulse_officer', raise_if_not_found=False)
            if group:
                target_partners = group.users.mapped('partner_id').ids
        if target_partners:
            self.env['bus.bus']._sendmany([
                (pid, 'simple_notification', {
                    'title': _('SendPulse: Нове повідомлення'),
                    'message': f"{self.service_icon} {self.name}: {self.last_message_preview or '...'}",
                    'sticky': False,
                })
                for pid in target_partners
            ])

    # ════════════════════════════════════════════════════════════════════
    # SendPulse API — відправка повідомлень
    # ════════════════════════════════════════════════════════════════════

    def _get_access_token(self):
        """OAuth2: отримує Bearer token від SendPulse."""
        ICP = self.env['ir.config_parameter'].sudo()
        client_id = ICP.get_param('odoo_chatwoot_connector.client_id', '')
        client_secret = ICP.get_param('odoo_chatwoot_connector.client_secret', '')
        if not client_id or not client_secret:
            _logger.warning('SendPulse Odo: не налаштовані client_id / client_secret')
            return None
        try:
            resp = requests.post(
                'https://api.sendpulse.com/oauth/access_token',
                json={
                    'grant_type': 'client_credentials',
                    'client_id': client_id,
                    'client_secret': client_secret,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get('access_token')
        except Exception as e:
            _logger.error('SendPulse Odo: помилка отримання токена: %s', e)
            return None

    # ════════════════════════════════════════════════════════════════════
    # Webhook Processing — викликається з controllers/main.py
    # ════════════════════════════════════════════════════════════════════

    @api.model
    def _process_incoming_event(self, data, contact, bot, service, event_type, timestamp_ms):
        """
        Обробляє вхідну подію з SendPulse webhook.
        Логіка:
          1. Шукаємо партнера по email або sendpulse_contact_id
          2. Якщо знайдено — прив'язуємо розмову до партнера
          3. Якщо ні — створюємо нову розмову в черзі "Не ідентифікований"
          4. Зберігаємо повідомлення
          5. Якщо розмова нова — створюємо discuss.channel
        """
        contact_id = contact.get('id', '')
        contact_name = contact.get('name', 'Невідомий')
        email = contact.get('email', '') or ''
        phone = contact.get('phone', '') or ''
        last_message = contact.get('last_message', '') or ''
        variables = contact.get('variables', {}) or {}

        # Соціальні ідентифікатори
        social_username = (
            variables.get('username') or
            variables.get('telegram_username') or
            contact.get('username', '')
        )
        social_profile_url = (
            variables.get('profile_url') or
            variables.get('facebook_url') or
            variables.get('instagram_url') or ''
        )

        # ── Крок 1: Ідентифікація партнера ──────────────────────────────
        partner = self._find_partner(contact_id, email, phone)

        # ── Крок 2: Знаходимо або створюємо розмову ─────────────────────
        connect = self.search([
            ('sendpulse_contact_id', '=', contact_id),
            ('service', '=', service),
            ('stage', '!=', 'close'),
        ], limit=1)

        now = fields.Datetime.now()
        if not connect:
            connect = self.create({
                'name': contact_name,
                'sendpulse_contact_id': contact_id,
                'service': service,
                'bot_id': bot.get('id', ''),
                'bot_name': bot.get('name', ''),
                'partner_id': partner.id if partner else False,
                'unidentified_email': email if not partner else False,
                'unidentified_phone': phone if not partner else False,
                'social_username': social_username or False,
                'social_profile_url': social_profile_url or False,
                'last_message_preview': last_message[:100] if last_message else '',
                'last_message_date': now,
                'stage': 'new',
            })
        else:
            # Оновлюємо існуючу розмову
            update_vals = {
                'last_message_preview': last_message[:100] if last_message else connect.last_message_preview,
                'last_message_date': now,
                'stage': 'new_message' if connect.stage == 'in_progress' else connect.stage,
            }
            if not connect.partner_id and partner:
                update_vals['partner_id'] = partner.id
            if social_username and not connect.social_username:
                update_vals['social_username'] = social_username
            if social_profile_url and not connect.social_profile_url:
                update_vals['social_profile_url'] = social_profile_url
            connect.write(update_vals)

        # ── Крок 3: Зберігаємо повідомлення ─────────────────────────────
        if last_message:
            self.env['sendpulse.message'].create({
                'name': now.strftime('%Y-%m-%d %H:%M'),
                'date': now,
                'connect_id': connect.id,
                'sendpulse_contact_id': contact_id,
                'direction': 'incoming',
                'message_type': 'text',
                'text_message': last_message,
                'raw_json': str({'text': last_message, 'contact': contact}),
            })

            # Якщо є активний channel — постимо туди для операторів
            if connect.channel_id:
                body = f"<b>👤 {contact_name}</b>:<br/>{last_message}"
                connect.channel_id.with_context(
                    sendpulse_incoming=True
                ).message_post(
                    body=body,
                    author_id=partner.id if partner else self.env.ref('base.partner_root').id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )

            # Зберігаємо у вкладці Messaging картки партнера
            if connect.partner_id:
                self.env['partner.sendpulse.message'].create({
                    'partner_id': connect.partner_id.id,
                    'date': now,
                    'text_message': f"<p>{last_message}</p>",
                    'service': service,
                    'direction': 'incoming',
                })

        # ── Крок 4: Оновлюємо канали партнера ───────────────────────────
        if connect.partner_id:
            connect._update_partner_source()

        # ── Крок 5: Якщо нова розмова — створюємо discuss.channel ───────
        if not connect.channel_id and event_type in ('new_subscriber', 'opened_live_chat'):
            connect._create_discuss_channel()

        return connect

    @api.model
    def _find_partner(self, contact_id, email, phone):
        """
        Шукає партнера в такому порядку пріоритетів:
        1. sendpulse_contact_id (якщо вже бачили цей контакт)
        2. email (основний ключ ідентифікації)
        3. phone
        """
        if contact_id:
            partner = self.env['res.partner'].search(
                [('sendpulse_contact_id', '=', contact_id)], limit=1
            )
            if partner:
                return partner

        if email:
            partner = self.env['res.partner'].search(
                [('email', '=ilike', email.strip())], limit=1
            )
            if partner:
                # Зберігаємо sendpulse_contact_id для майбутніх пошуків
                if not partner.sendpulse_contact_id:
                    partner.write({'sendpulse_contact_id': contact_id})
                return partner

        if phone:
            clean_phone = phone.strip().replace(' ', '')
            partner = self.env['res.partner'].search(
                ['|', ('phone', '=', clean_phone), ('mobile', '=', clean_phone)], limit=1
            )
            if partner:
                if not partner.sendpulse_contact_id:
                    partner.write({'sendpulse_contact_id': contact_id})
                return partner

        return None

    @api.model
    def _process_unsubscribe(self, contact_id, service):
        """Відмічає розмову як закриту при відписці клієнта."""
        connects = self.search([
            ('sendpulse_contact_id', '=', contact_id),
            ('service', '=', service),
            ('stage', '!=', 'close'),
        ])
        for connect in connects:
            connect.write({'stage': 'close'})
            _logger.info(
                'SendPulse Odo: контакт %s відписався (%s), розмова закрита',
                contact_id, service,
            )

    def send_message_to_sendpulse(self, text, attachment_url=None):
        """
        Відправляє текстове повідомлення клієнту через SendPulse API.
        Викликається з mail_channel.py при відповіді оператора в Discuss.
        """
        self.ensure_one()
        if not self.sendpulse_contact_id:
            _logger.warning('SendPulse Odo: немає contact_id для відправки')
            return False

        token = self._get_access_token()
        if not token:
            return False

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }

        # Маршрутизація по сервісу
        service = self.service or 'telegram'
        endpoint_map = {
            'telegram': 'https://api.sendpulse.com/telegram/contacts/send',
            'instagram': 'https://api.sendpulse.com/instagram/contacts/send',
            'facebook': 'https://api.sendpulse.com/facebook/contacts/send',
            'messenger': 'https://api.sendpulse.com/facebook/contacts/send',
            'viber': 'https://api.sendpulse.com/viber/contacts/send',
            'whatsapp': 'https://api.sendpulse.com/whatsapp/contacts/send',
            'livechat': 'https://api.sendpulse.com/livechat/contacts/send',
        }
        endpoint = endpoint_map.get(service, endpoint_map['telegram'])

        payload = {
            'contact_id': self.sendpulse_contact_id,
            'messages': [{'type': 'text', 'text': {'text': text}}],
        }
        if attachment_url:
            payload['messages'].append({
                'type': 'image',
                'image': {'url': attachment_url},
            })

        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=15)
            resp.raise_for_status()
            _logger.info('SendPulse Odo: повідомлення відправлено контакту %s', self.sendpulse_contact_id)
            return True
        except Exception as e:
            _logger.error('SendPulse Odo: помилка відправки: %s', e)
            return False
