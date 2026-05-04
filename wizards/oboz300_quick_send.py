"""
OBOZ300 Quick Send Wizard — manager fills 4 fields, clicks "Send", coupon
goes out (email + SMS + loyalty.card + RODO via existing automation 1316).

Use case: PL Lead Magnet 2026 manual lead intake while Meta App Review
for leads_retrieval permission is pending.
"""

import logging
import re

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _normalize_phone(phone):
    if not phone:
        return ''
    return re.sub(r'[^\d+]', '', phone)


class OBOZ300QuickSend(models.TransientModel):
    _name = 'oboz300.quick.send'
    _description = 'OBOZ300 Quick Send Coupon Wizard'

    contact_name = fields.Char('Imię i nazwisko', required=True)
    email = fields.Char('Email', required=True)
    phone = fields.Char('Telefon')
    wiek_dziecka = fields.Char('Wiek dziecka', help='Np. "10-12 lat"')
    miasto = fields.Char('Miasto')
    oboz = fields.Char('Obóz, który Cię interesuje')
    source = fields.Selection(
        [
            ('meta_lead_form', 'Meta Lead Ad (manual import)'),
            ('landing_form', 'campscout.pl form'),
            ('phone_call', 'Phone call'),
            ('admin_manual', 'Other manual'),
        ],
        default='meta_lead_form',
        string='Źródło leada',
        required=True,
    )

    def action_send(self):
        """Create crm.lead → existing automation 1316 fires the OBOZ300 pipeline."""
        self.ensure_one()
        if not self.email and not self.phone:
            raise UserError(_('Należy podać email lub telefon.'))

        phone = _normalize_phone(self.phone or '')

        Partner = self.env['res.partner']
        partner = Partner.search(
            [
                ('email', '=ilike', self.email),
                ('user_ids', '=', False),
                ('is_company', '=', False),
            ],
            limit=1,
        )
        if not partner:
            country_pl = self.env['res.country'].search([('code', '=', 'PL')], limit=1)
            partner = Partner.create(
                {
                    'name': self.contact_name,
                    'email': self.email or False,
                    'phone': phone or False,
                    'lang': 'pl_PL',
                    'is_company': False,
                    'country_id': country_pl.id if country_pl else False,
                }
            )

        description_lines = [
            f'Źródło: {dict(self._fields["source"].selection).get(self.source, self.source)}',
            f'Wiek dziecka: {self.wiek_dziecka}' if self.wiek_dziecka else '',
            f'Miasto: {self.miasto}' if self.miasto else '',
            f'Obóz: {self.oboz}' if self.oboz else '',
            f'Manual entry by {self.env.user.name} via Quick Send wizard',
        ]
        description = '\n'.join(line for line in description_lines if line.strip())

        prefix = 'Zgłoszenie META PL' if self.source == 'meta_lead_form' else 'Zgłoszenie PL'
        lead = self.env['crm.lead'].create(
            {
                'name': f'{prefix}: {self.contact_name}',
                'contact_name': self.contact_name,
                'phone': phone or False,
                'email_from': self.email or False,
                'description': description,
                'type': 'lead',
                'partner_id': partner.id,
            }
        )

        _logger.info(
            'OBOZ300 quick-send: lead %s created by %s for %s (source=%s)',
            lead.id,
            self.env.user.login,
            self.email,
            self.source,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Lead created'),
            'res_model': 'crm.lead',
            'res_id': lead.id,
            'view_mode': 'form',
            'target': 'current',
        }
