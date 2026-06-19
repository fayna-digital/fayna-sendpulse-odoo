import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ── SendPulse ідентифікатор ─────────────────────────────────────────
    sendpulse_contact_id = fields.Char(
        string='SendPulse Contact ID',
        index=True,
        help='UUID контакту в SendPulse (первинний ключ для ідентифікації)',
    )

    # ── Список ВСІХ каналів партнера (кожен канал — окремий рядок) ──────
    sendpulse_channel_ids = fields.One2many(
        'partner.sendpulse.channel',
        'partner_id',
        string='Канали SendPulse',
        help='Всі соціальні канали через які клієнт писав у SendPulse',
    )
    sendpulse_channel_count = fields.Integer(
        string='Кількість каналів',
        compute='_compute_sendpulse_channel_count',
    )

    # ── Список ВСІХ розмов ──────────────────────────────────────────────
    sendpulse_connect_ids = fields.One2many(
        'sendpulse.connect',
        'partner_id',
        string='Розмови SendPulse',
    )
    sendpulse_connect_count = fields.Integer(
        string='Розмов',
        compute='_compute_sendpulse_connect_count',
    )

    # ── Список повідомлень у вкладці Messaging ──────────────────────────
    sendpulse_message_ids = fields.One2many(
        'partner.sendpulse.message',
        'partner_id',
        string='Повідомлення SendPulse',
    )

    def _compute_sendpulse_channel_count(self):
        for rec in self:
            rec.sendpulse_channel_count = len(rec.sendpulse_channel_ids)

    def _compute_sendpulse_connect_count(self):
        for rec in self:
            rec.sendpulse_connect_count = len(rec.sendpulse_connect_ids)

    def action_open_sendpulse_connects(self):
        """Відкриває всі розмови SendPulse для цього партнера."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Розмови SendPulse'),
            'res_model': 'sendpulse.connect',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    # ── Оферта-каталог: посилання на завантаження (БЕЗ важкого вкладення) ──
    def _offer_catalog_download_url(self):
        """URL завантаження каталогу. Конфіг-driven, без хардкоду:
        1) явний param offer_catalog_url (зовнішній статичний URL), або
        2) збудований з ir.attachment (param lead_magnet_pdf_attachment_id) + access_token.
        Повертає '' якщо нічого не налаштовано."""
        ICP = self.env['ir.config_parameter'].sudo()
        explicit = (ICP.get_param('odoo_chatwoot_connector.offer_catalog_url') or '').strip()
        if explicit:
            return explicit
        att_id_raw = ICP.get_param('odoo_chatwoot_connector.lead_magnet_pdf_attachment_id', '')
        try:
            att = self.env['ir.attachment'].sudo().browse(int(att_id_raw))
        except (TypeError, ValueError):
            return ''
        if not att.exists():
            return ''
        token = att.access_token or att.generate_access_token()[0]
        base = ICP.get_param('web.base.url', 'https://campscout.eu').rstrip('/')
        return f'{base}/web/content/{att.id}?download=true&access_token={token}'

    def _send_offer_catalog(self, to_email=None, source='manual'):
        """Channel-independent надсилання PL-оферти з ПОСИЛАННЯМ на каталог.
        Викликають обидва шляхи: F13 (через partner_id) і кнопка на картці клієнта.
        self — partner (для персоналізації/рендеру), може бути порожнім recordset.
        Повертає {'ok','error','message_id'}."""
        partner = self[:1]
        to_email = (to_email or (partner.email if partner else '') or '').strip()
        if not to_email:
            return {'ok': False, 'error': 'no_email', 'message_id': None}
        url = (partner or self.env['res.partner'])._offer_catalog_download_url()
        if not url:
            return {'ok': False, 'error': 'no_catalog_configured', 'message_id': None}
        tpl = self.env.ref(
            'odoo_chatwoot_connector.mail_template_offer_pl', raise_if_not_found=False
        )
        try:
            if tpl and partner:
                rendered = (
                    tpl.sudo()
                    ._generate_template([partner.id], ['subject', 'body_html', 'email_from'])
                    .get(partner.id, {})
                )
                body = (rendered.get('body_html') or '').replace('__DOWNLOAD_URL__', url)
                subject = rendered.get('subject') or 'CampScout — katalog obozów Lato 2026'
                email_from = rendered.get('email_from') or 'CampScout <obozy@campscout.pl>'
            else:
                subject = 'CampScout — katalog obozów Lato 2026 🏕️'
                body = (
                    '<p>Dzień dobry!</p>'
                    '<p>Katalog obozów CampScout 2026: '
                    f'<a href="{url}" target="_blank">📄 Pobierz katalog (PDF)</a></p>'
                    '<p>campscout.pl</p>'
                )
                email_from = 'CampScout <obozy@campscout.pl>'
            mail_vals = {
                'subject': subject,
                'body_html': body,
                'email_to': to_email,
                'email_from': email_from,
                'auto_delete': False,
            }
            if partner:  # трасування листа в картці клієнта
                mail_vals.update({'model': 'res.partner', 'res_id': partner.id})
            mail = self.env['mail.mail'].sudo().create(mail_vals)
            mail.send(raise_exception=False)
        except Exception as e:
            _logger.warning('CampScout offer email exception — %s', e)
            return {'ok': False, 'error': f'exception:{e}', 'message_id': None}
        # RODO audit для РУЧНОГО шляху (F13 робить власний record_consent).
        if source == 'manual':
            try:
                self.env['sendpulse.privacy.consent.log'].sudo().create({
                    'partner_id': partner.id if partner else False,
                    'email': to_email.lower(),
                    'purpose': 'lead_magnet_email',
                    'consent_given': True,
                    'notes': 'Offer catalog (PL link) sent manually by operator',
                })
            except Exception as e:
                _logger.info('CampScout offer consent-log skip — %s', e)
        return {'ok': True, 'error': None, 'message_id': mail.id}

    def action_send_offer_catalog(self):
        """Кнопка «Wyślij ofertę» на картці клієнта — працює і для вручну створених."""
        self.ensure_one()
        if not self.email:
            raise UserError(_(
                'Brak adresu e-mail u klienta — uzupełnij e-mail przed wysłaniem oferty.'
            ))
        res = self._send_offer_catalog(self.email, source='manual')
        if not res.get('ok'):
            errmap = {
                'no_email': _('Brak adresu e-mail'),
                'no_catalog_configured': _(
                    'Katalog nie jest skonfigurowany — ustaw załącznik PDF lub URL w ustawieniach.'
                ),
            }
            raise UserError(errmap.get(res.get('error'), res.get('error') or _('Błąd wysyłki')))
        self.message_post(body=_('📄 Oferta (katalog PDF, link) wysłana na %s') % self.email)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Wysłano'),
                'message': _('Oferta wysłana na %s') % self.email,
                'type': 'success',
                'sticky': False,
            },
        }
