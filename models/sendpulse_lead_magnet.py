import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SendpulseConnectLeadMagnet(models.Model):
    _inherit = 'sendpulse.connect'

    # ── V2 F13: Lead magnet — PDF-каталог + SMS-купон ─────────────────────
    def _send_pdf_catalog_email(self, to_email=None):
        """
        Надсилає lead-magnet PDF-каталог на email клієнта.
        Повертає {'ok': bool, 'error': str or None, 'message_id': int or None}.
        Ідемпотентно — якщо sp_pdf_sent_at уже встановлено на цей email, skip.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.lead_magnet_enabled', 'False') != 'True':
            return {'ok': False, 'error': 'disabled', 'message_id': None}
        to_email = (
            to_email or self.sp_booking_email or (self.partner_id.email if self.partner_id else '')
        ).strip()
        if not to_email:
            return {'ok': False, 'error': 'no_email', 'message_id': None}
        # Idempotency
        if self.sp_pdf_sent_at and self.sp_pdf_sent_to_email == to_email:
            return {'ok': True, 'error': 'already_sent', 'message_id': None}

        # RODO/GDPR: перед send — перевірити явне відкликання згоди.
        # Якщо клієнт писав «STOP» / «отписка» / «nie chcę» — skip.
        # Якщо consent record відсутній — трактуємо надання email як неявну
        # згоду (unambiguous action per art. 4(11) RODO) і фіксуємо її.
        ConsentLog = self.env['sendpulse.privacy.consent.log'].sudo()
        enforce_consent = (
            ICP.get_param('odoo_chatwoot_connector.consent_enforcement_enabled', 'True') == 'True'
        )
        if enforce_consent:
            last_consent = ConsentLog.search(
                [
                    ('purpose', '=', 'lead_magnet_email'),
                    ('email', '=', to_email.lower()),
                ],
                order='consent_timestamp desc, id desc',
                limit=1,
            )
            if last_consent and not last_consent.consent_given:
                _logger.info(
                    'SendPulse Odoo: F13 PDF skip — consent withdrawn for %s',
                    to_email,
                )
                return {'ok': False, 'error': 'consent_withdrawn', 'message_id': None}

        att_id_raw = ICP.get_param('odoo_chatwoot_connector.lead_magnet_pdf_attachment_id', '')
        try:
            att_id = int(att_id_raw)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'no_attachment_configured', 'message_id': None}
        attachment = self.env['ir.attachment'].sudo().browse(att_id)
        if not attachment.exists() or not attachment.datas:
            return {'ok': False, 'error': 'attachment_missing', 'message_id': None}

        # Надсилаємо PL-оферту з ПОСИЛАННЯМ на каталог (без важкого вкладення —
        # уникаємо SMTP 552 "message size"). Делегуємо channel-independent методу
        # на res.partner; F13-специфічний RODO-запис (record_consent) — нижче.
        partner = self.partner_id or self.env['res.partner']
        res = partner._send_offer_catalog(to_email, source='f13')
        if not res.get('ok'):
            _logger.warning('SendPulse Odoo: F13 offer email failed — %s', res.get('error'))
            return res
        self.sudo().write(
            {
                'sp_pdf_sent_at': fields.Datetime.now(),
                'sp_pdf_sent_to_email': to_email,
            }
        )
        # RODO: фіксуємо згоду як факт — email був наданий клієнтом у чаті
        # з метою отримати каталог (unambiguous action per art. 4(11)).
        # Беремо останнє incoming повідомлення як доказ.
        if enforce_consent:
            last_in_msg = (
                self.env['sendpulse.message']
                .sudo()
                .search(
                    [
                        ('connect_id', '=', self.id),
                        ('direction', '=', 'incoming'),
                    ],
                    order='date desc, id desc',
                    limit=1,
                )
            )
            ConsentLog.record_consent(
                purpose='lead_magnet_email',
                channel='email',
                partner_id=self.partner_id.id if self.partner_id else False,
                connect_id=self.id,
                message_id=last_in_msg.id if last_in_msg else False,
                email=to_email,
                consent_given=True,
                exact_response=(last_in_msg.text_message or to_email) if last_in_msg else to_email,
                notes=f'Auto-recorded on PDF send for connect {self.id}',
            )
        _logger.info(
            'SendPulse Odoo: F13 PDF sent to %s for connect %s',
            to_email,
            self.id,
        )
        return {'ok': True, 'error': None, 'message_id': res.get('message_id')}

    def _get_email_logo_png_b64(self, company):
        """
        Повертає base64-PNG логотипа для email. Gmail не рендерить SVG,
        тому `res.company.logo` (SVG у CampScout) не годиться — віддаємо
        shipped PNG з модуля (static/src/img/campscout_logo.png). Fallback
        на company.logo якщо PNG в модулі немає.
        """
        import base64
        import os

        module_root = os.path.dirname(os.path.dirname(__file__))
        png_path = os.path.join(module_root, 'static', 'src', 'img', 'campscout_logo.png')
        if os.path.exists(png_path):
            try:
                with open(png_path, 'rb') as f:
                    return base64.b64encode(f.read())
            except Exception as e:
                _logger.warning('SendPulse Odoo: cannot read shipped logo — %s', e)
        if company and company.logo:
            try:
                raw = base64.b64decode(company.logo[:30])
                # Якщо company.logo растровий (PNG/JPEG) — годиться
                if raw.startswith(b'\x89PNG') or raw.startswith(b'\xff\xd8\xff'):
                    return company.logo
            except Exception:
                pass
        return False

    def _get_or_create_public_image(self, name, image_b64):
        """
        Створити (або знайти) публічний ir.attachment для inline-картинки в email.
        Кеш — в ir.config_parameter (lead_magnet_{name}_attachment_id).
        Автоматично пересоздає якщо картинка змінилась (checksum mismatch).
        Повертає ir.attachment recordset (може бути empty).
        """
        if not image_b64:
            return self.env['ir.attachment'].sudo()
        ICP = self.env['ir.config_parameter'].sudo()
        key = f'odoo_chatwoot_connector.{name}_attachment_id'
        att_id_raw = ICP.get_param(key, '')
        try:
            att_id = int(att_id_raw)
        except (TypeError, ValueError):
            att_id = 0
        Att = self.env['ir.attachment'].sudo()
        if att_id:
            att = Att.browse(att_id)
            if att.exists() and att.public and att.datas == image_b64:
                return att
        att = Att.create(
            {
                'name': f'{name}.png',
                'datas': image_b64,
                'mimetype': 'image/png',
                'res_model': 'ir.ui.view',
                'res_id': 0,
                'public': True,
            }
        )
        ICP.set_param(key, str(att.id))
        return att

    def _generate_and_send_sms_coupon(self, to_phone=None):
        """
        Надсилає SMS зі shared-купоном lead_magnet_coupon_program_id.
        Один код на всіх клієнтів — спільний pool, Odoo loyalty знижує
        points на кожному використанні.

        Повертає {'ok', 'error', 'code', 'remaining', 'expires'}.
        Ідемпотентно — якщо клієнту SMS уже надіслано, повертає existing.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        empty = {'ok': False, 'error': '', 'code': '', 'remaining': 0, 'expires': ''}
        if ICP.get_param('odoo_chatwoot_connector.lead_magnet_enabled', 'False') != 'True':
            return {**empty, 'error': 'disabled'}
        to_phone = (
            to_phone
            or (self.partner_id.mobile or self.partner_id.phone if self.partner_id else '')
            or ''
        ).strip()
        if not to_phone:
            return {**empty, 'error': 'no_phone'}
        # Idempotency: той самий клієнт — той самий код (shared pool)
        if self.sp_coupon_code and self.sp_coupon_sent_at:
            return {**empty, 'ok': True, 'error': 'already_sent', 'code': self.sp_coupon_code}

        # RODO/PKE: SMS — окремий канал, потрібна окрема згода.
        ConsentLog = self.env['sendpulse.privacy.consent.log'].sudo()
        enforce_consent = (
            ICP.get_param('odoo_chatwoot_connector.consent_enforcement_enabled', 'True') == 'True'
        )
        if enforce_consent:
            last_consent = ConsentLog.search(
                [
                    ('purpose', '=', 'lead_magnet_sms'),
                    ('phone', '=', to_phone),
                ],
                order='consent_timestamp desc, id desc',
                limit=1,
            )
            if last_consent and not last_consent.consent_given:
                _logger.info(
                    'SendPulse Odoo: F13 SMS skip — consent withdrawn for %s',
                    to_phone,
                )
                return {**empty, 'error': 'consent_withdrawn'}

        program_id_raw = ICP.get_param('odoo_chatwoot_connector.lead_magnet_coupon_program_id', '')
        try:
            program_id = int(program_id_raw)
        except (TypeError, ValueError):
            return {**empty, 'error': 'no_program_configured'}
        program = self.env['loyalty.program'].sudo().browse(program_id)
        if not program.exists():
            return {**empty, 'error': 'program_missing'}

        # Беремо shared card програми (перший active card з points > 0).
        # Якщо нема — fallback: створюємо одну spільну.
        card = (
            self.env['loyalty.card']
            .sudo()
            .search(
                [('program_id', '=', program.id), ('points', '>', 0)],
                order='id',
                limit=1,
            )
        )
        if not card:
            card = (
                self.env['loyalty.card']
                .sudo()
                .search(
                    [('program_id', '=', program.id)],
                    order='id desc',
                    limit=1,
                )
            )
            if not card:
                try:
                    card = (
                        self.env['loyalty.card']
                        .sudo()
                        .create(
                            {
                                'program_id': program.id,
                                'points': 100.0,
                            }
                        )
                    )
                except Exception as e:
                    return {**empty, 'error': f'coupon_create:{e}'}
        code = card.code
        remaining = int(card.points) if card.points is not None else 0
        expires_str = card.expiration_date.strftime('%d.%m.%Y') if card.expiration_date else ''

        if remaining <= 0:
            return {**empty, 'error': 'coupon_exhausted', 'code': code, 'expires': expires_str}

        # Compose SMS text
        sms_tmpl = ICP.get_param(
            'odoo_chatwoot_connector.lead_magnet_sms_template',
            '',
        ) or (
            'CampScout: код 5% знижки — {code}. Залишилось {remaining} '
            'купонів! Діє до {expires}. Оформляйте: campscout.eu'
        )
        sms_text = (
            sms_tmpl.replace('{code}', code)
            .replace('{remaining}', str(remaining))
            .replace('{expires}', expires_str or '01.07.2026')
        )

        # Send via kw_sms_api (TurboSMS) — sms.sms record with kw_sms_provider_id set
        sms_provider_id = ICP.get_param('odoo_chatwoot_connector.sms_provider_id', '')
        try:
            sms_provider_id = int(sms_provider_id)
        except (TypeError, ValueError):
            sms_provider_id = False

        sms_vals = {
            'number': to_phone,
            'body': sms_text[:300],
            'partner_id': self.partner_id.id if self.partner_id else False,
        }
        # kw_sms_api додає поле kw_sms_provider_id — ставимо якщо налаштовано
        if sms_provider_id and 'kw_sms_provider_id' in self.env['sms.sms']._fields:
            sms_vals['kw_sms_provider_id'] = sms_provider_id
        try:
            sms = self.env['sms.sms'].sudo().create(sms_vals)
            sms.send()
        except Exception as e:
            _logger.warning('SendPulse Odoo: F13 SMS send exception — %s', e)
            return {'ok': False, 'error': f'sms_send:{e}', 'code': code}

        self.sudo().write(
            {
                'sp_coupon_code': code,
                'sp_coupon_sent_at': fields.Datetime.now(),
                'sp_coupon_sent_to_phone': to_phone,
            }
        )
        # RODO/PKE: фіксуємо SMS-консент (окремий канал від email).
        if enforce_consent:
            last_in_msg = (
                self.env['sendpulse.message']
                .sudo()
                .search(
                    [
                        ('connect_id', '=', self.id),
                        ('direction', '=', 'incoming'),
                    ],
                    order='date desc, id desc',
                    limit=1,
                )
            )
            ConsentLog.record_consent(
                purpose='lead_magnet_sms',
                channel='sms',
                partner_id=self.partner_id.id if self.partner_id else False,
                connect_id=self.id,
                message_id=last_in_msg.id if last_in_msg else False,
                phone=to_phone,
                consent_given=True,
                exact_response=(last_in_msg.text_message or to_phone) if last_in_msg else to_phone,
                notes=f'Auto-recorded on SMS coupon send for connect {self.id}',
            )
        _logger.info(
            'SendPulse Odoo: F13 coupon %s sent to %s for connect %s (remaining=%d)',
            code,
            to_phone,
            self.id,
            remaining,
        )
        return {
            'ok': True,
            'error': None,
            'code': code,
            'remaining': remaining,
            'expires': expires_str,
        }

    @api.model
    def send_pdf_catalog_for_channel(self, channel_id, to_email=None):
        """RPC для OWL-панелі. Надсилає PDF-каталог на email."""
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect:
            return {'ok': False, 'error': 'no_connect', 'message_id': None}
        return connect._send_pdf_catalog_email(to_email=to_email)

    @api.model
    def send_sms_coupon_for_channel(self, channel_id, to_phone=None):
        """RPC для OWL-панелі. Генерує coupon + SMS."""
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect:
            return {'ok': False, 'error': 'no_connect', 'code': ''}
        return connect._generate_and_send_sms_coupon(to_phone=to_phone)

