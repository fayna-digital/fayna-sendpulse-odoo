# -*- coding: utf-8 -*-
import random
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class SendpulsePublicTemplate(models.Model):
    _name = 'sendpulse.public.template'
    _description = 'SendPulse публічний шаблон (A/B tracking)'
    _order = 'sequence, id'

    name = fields.Char(string='Назва', required=True, translate=False)
    text = fields.Text(
        string='Текст шаблону', required=True,
        help='Placeholders: {landing_url}, {tg_url} — підставляються з Settings.',
    )
    kind = fields.Selection(
        [('standard', 'Стандартний'), ('repeat', 'Повторний контакт')],
        default='standard', required=True,
        help='repeat — використовується коли клієнт вже писав у приват цьому ж контакту.',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    use_count = fields.Integer(
        string='Використано', default=0, readonly=True,
        help='Скільки разів цей шаблон публікувався під коментарями.',
    )
    customer_replied_count = fields.Integer(
        string='Конверсій', default=0, readonly=True,
        help='Скільки клієнтів після публічної відповіді написали у приват.',
    )
    conversion_rate = fields.Float(
        string='Конверсія, %', compute='_compute_conversion_rate', store=True,
        digits=(6, 2),
    )
    last_used_at = fields.Datetime(string='Востаннє використано', readonly=True)

    _sql_constraints = [
        ('name_uniq', 'UNIQUE(name)', 'Назва шаблону має бути унікальною.'),
    ]

    @api.depends('use_count', 'customer_replied_count')
    def _compute_conversion_rate(self):
        for rec in self:
            rec.conversion_rate = (
                (rec.customer_replied_count / rec.use_count * 100.0)
                if rec.use_count else 0.0
            )

    @api.model
    def pick_template(self, is_repeat=False):
        """
        Повертає один active template. Epsilon-greedy:
          - Перші 50 загальних use_count — round-robin (набираємо дані).
          - Далі: 80% найкращий за conversion, 20% random explore.
        Якщо is_repeat=True — повертає перший active template з kind='repeat'.
        """
        domain = [('active', '=', True), ('kind', '=', 'repeat' if is_repeat else 'standard')]
        templates = self.search(domain, order='sequence, id')
        if not templates:
            return self.browse()
        if is_repeat or len(templates) == 1:
            return templates[0]

        total_use = sum(templates.mapped('use_count'))
        if total_use < 50:
            # Round-robin за loc — щоб рівномірно набрати статистику
            idx = total_use % len(templates)
            return templates[idx]

        # Epsilon-greedy
        if random.random() < 0.2:
            return random.choice(templates)
        ranked = templates.sorted(key='conversion_rate', reverse=True)
        return ranked[0]

    def bump_use(self):
        """Інкремент use_count + last_used_at. Викликається при публікації."""
        now = fields.Datetime.now()
        for rec in self:
            rec.sudo().write({
                'use_count': rec.use_count + 1,
                'last_used_at': now,
            })

    def bump_customer_replied(self):
        """Інкремент customer_replied_count. Викликається при переході funnel → customer_replied."""
        for rec in self:
            rec.sudo().write({
                'customer_replied_count': rec.customer_replied_count + 1,
            })
