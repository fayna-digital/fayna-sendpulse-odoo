# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class SendpulseIdentifyWizard(models.TransientModel):
    """
    Wizard для ідентифікації клієнта в розмові SendPulse.
    Дозволяє:
      1. Знайти існуючого партнера за email або телефоном → прив'язати
      2. Створити нового партнера якщо не знайдено
      3. Відкрити картку партнера для ручного merge дублікатів
    """
    _name = 'sendpulse.identify.wizard'
    _description = 'Ідентифікація клієнта SendPulse'

    connect_id = fields.Many2one(
        'sendpulse.connect', string='Розмова', required=True, ondelete='cascade',
    )

    # ── Відображення даних з SendPulse ──────────────────────────────────
    connect_name = fields.Char(
        string='Ім\'я з SendPulse', related='connect_id.name', readonly=True,
    )
    connect_service = fields.Selection(
        related='connect_id.service', readonly=True, string='Канал',
    )

    # ── Поля пошуку ─────────────────────────────────────────────────────
    search_email = fields.Char(string='Email')
    search_phone = fields.Char(string='Телефон')

    # ── Результати пошуку ────────────────────────────────────────────────
    search_done = fields.Boolean(default=False)
    found_partner_ids = fields.Many2many(
        'res.partner',
        'sendpulse_wizard_partner_rel', 'wizard_id', 'partner_id',
        string='Знайдені клієнти',
    )
    selected_partner_id = fields.Many2one(
        'res.partner', string='Обраний клієнт',
    )
    found_count = fields.Integer(
        string='Кількість знайдених', compute='_compute_found_count',
    )

    @api.depends('found_partner_ids')
    def _compute_found_count(self):
        for rec in self:
            rec.found_count = len(rec.found_partner_ids)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        connect_id = vals.get('connect_id') or self.env.context.get('default_connect_id')
        if connect_id:
            connect = self.env['sendpulse.connect'].browse(connect_id)
            vals['search_email'] = connect.unidentified_email or ''
            vals['search_phone'] = connect.unidentified_phone or ''
        return vals

    # ════════════════════════════════════════════════════════════════════
    # Дії
    # ════════════════════════════════════════════════════════════════════

    def action_search(self):
        """Шукає партнерів за email, телефоном або іменем (часткове співпадіння)."""
        self.ensure_one()
        domain = []

        if self.search_email and self.search_email.strip():
            term = self.search_email.strip()
            # Пошук по email (частковий) АБО по імені
            domain = ['|', ('email', 'ilike', term), ('name', 'ilike', term)]
        elif self.search_phone and self.search_phone.strip():
            clean = self.search_phone.strip().replace(' ', '').replace('-', '')
            domain = ['|', '|', ('phone', 'ilike', clean), ('mobile', 'ilike', clean), ('name', 'ilike', clean)]

        if domain:
            partners = self.env['res.partner'].search(domain + [('active', '=', True)], limit=20)
        else:
            partners = self.env['res.partner']

        self.write({
            'found_partner_ids': [(6, 0, partners.ids)],
            'selected_partner_id': partners[0].id if len(partners) == 1 else False,
            'search_done': True,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_link_partner(self):
        """Прив'язує обраного партнера до розмови."""
        self.ensure_one()
        if not self.selected_partner_id:
            raise UserError(_('Оберіть клієнта зі списку знайдених.'))

        partner = self.selected_partner_id
        # Зберігаємо sendpulse_contact_id якщо його ще немає
        if not partner.sendpulse_contact_id and self.connect_id.sendpulse_contact_id:
            partner.write({'sendpulse_contact_id': self.connect_id.sendpulse_contact_id})

        self.connect_id.assign_partner(partner.id)
        self.connect_id.write({
            'stage': 'in_progress',
            'unidentified_email': False,
            'unidentified_phone': False,
        })
        return {'type': 'ir.actions.act_window_close'}

    def action_create_and_link(self):
        """Створює нового партнера і прив'язує до розмови."""
        self.ensure_one()
        vals = {
            'name': self.connect_id.name,
        }
        if self.search_email:
            vals['email'] = self.search_email.strip()
        elif self.connect_id.unidentified_email:
            vals['email'] = self.connect_id.unidentified_email

        if self.search_phone:
            vals['phone'] = self.search_phone.strip()
        elif self.connect_id.unidentified_phone:
            vals['phone'] = self.connect_id.unidentified_phone

        partner = self.env['res.partner'].sudo().create(vals)
        # Прив'язуємо sendpulse_contact_id одразу
        if self.connect_id.sendpulse_contact_id:
            partner.sudo().write({'sendpulse_contact_id': self.connect_id.sendpulse_contact_id})

        self.connect_id.assign_partner(partner.id)
        self.connect_id.write({
            'stage': 'in_progress',
            'unidentified_email': False,
            'unidentified_phone': False,
        })

        # Відкриваємо картку нового партнера щоб можна було перевірити / merge
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': partner.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_partner(self):
        """Відкриває картку обраного партнера (для перевірки / merge)."""
        self.ensure_one()
        partner = self.selected_partner_id or (
            self.found_partner_ids[0] if self.found_partner_ids else None
        )
        if not partner:
            raise UserError(_('Спочатку оберіть клієнта зі списку.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': partner.id,
            'view_mode': 'form',
            'target': 'new',
        }
