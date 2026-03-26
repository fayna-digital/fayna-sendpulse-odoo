# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


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
        'partner.sendpulse.channel', 'partner_id',
        string='Канали SendPulse',
        help='Всі соціальні канали через які клієнт писав у SendPulse',
    )
    sendpulse_channel_count = fields.Integer(
        string='Кількість каналів',
        compute='_compute_sendpulse_channel_count',
    )

    # ── Список ВСІХ розмов ──────────────────────────────────────────────
    sendpulse_connect_ids = fields.One2many(
        'sendpulse.connect', 'partner_id',
        string='Розмови SendPulse',
    )
    sendpulse_connect_count = fields.Integer(
        string='Розмов',
        compute='_compute_sendpulse_connect_count',
    )

    # ── Список повідомлень у вкладці Messaging ──────────────────────────
    sendpulse_message_ids = fields.One2many(
        'partner.sendpulse.message', 'partner_id',
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
