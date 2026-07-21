"""
SendPulse ↔ Odoo — Reporting shard.

`_inherit`-шматок `sendpulse.connect` (God Object рефакторинг, крок 12/14):
крони звітності — live-звірка dialogs-снепшоту SendPulse проти sendpulse.message
(cron_check_dialogs_snapshot) і тижневий Telegram funnel-звіт
(cron_weekly_telegram_report + допоміжні _calculate_weekly_stats/_format_weekly_report).
Мовна логіка не змінена — чистий перенос коду з sendpulse_connect.py.
"""

import logging
from datetime import datetime, timedelta

import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SendpulseConnectReporting(models.Model):
    _inherit = 'sendpulse.connect'

    _DIALOGS_URL = 'https://api.sendpulse.com/chatbots/dialogs'

    @api.model
    def cron_check_dialogs_snapshot(self):
        """
        Cron: щодня тягне ~100 найсвіжіших діалогів через офіційний
        GET /chatbots/dialogs (SendPulse Chatbots API) і звіряє
        last_inbox_message кожного з тим, що є в sendpulse.message.

        Доповнює cron_check_message_gap (модель sendpulse.webhook.data):
        той працює лише в межах власної 30-денної ретенції і лише на
        тому, що ми самі встигли зберегти ДО можливого збою. Цей — живий
        снепшот прямо з SendPulse, незалежний від нашої ретенції і від
        того, чи взагалі дійшов webhook.

        API /dialogs НЕ має фільтра по contact_id чи даті (тільки
        size/skip/search_after/order — перевірено живою OpenAPI-специфою
        SendPulse) — тому просто найсвіжіші order=desc, без спроби
        охопити всю історію. Затримка 5 хв — той самий сенс, що в
        cron_check_message_gap: дати обробці домовитись, не false-positive
        на щойно прийнятому.
        """
        token = self._get_access_token()
        if not token:
            _logger.warning('SendPulse Odoo: dialogs-снепшот пропущено — немає токена API')
            return
        try:
            resp = requests.get(
                self._DIALOGS_URL,
                params={'size': 100, 'order': 'desc'},
                headers={'Authorization': f'Bearer {token}'},
                timeout=15,
            )
            resp.raise_for_status()
            dialogs = (resp.json().get('data') or {}).get('list') or []
        except Exception as e:
            _logger.warning('SendPulse Odoo: dialogs-снепшот — помилка API: %s', e)
            return

        now_utc = datetime.utcnow()
        gaps = []
        for d in dialogs:
            inbox = d.get('last_inbox_message') or {}
            text = (inbox.get('text') or '').strip()
            date_str = inbox.get('date')
            contact = d.get('contact') or {}
            contact_id = contact.get('id')
            if not (text and date_str and contact_id):
                continue
            try:
                sp_date = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S.%fZ')
            except ValueError:
                continue
            if now_utc - sp_date < timedelta(minutes=5):
                continue
            exists = (
                self.env['sendpulse.message']
                .sudo()
                .search_count(
                    [
                        ('sendpulse_contact_id', '=', contact_id),
                        ('direction', '=', 'incoming'),
                        ('date', '>=', sp_date - timedelta(minutes=3)),
                        ('date', '<=', sp_date + timedelta(minutes=3)),
                    ]
                )
            )
            if not exists:
                gaps.append(
                    {
                        'name': contact.get('full_name') or contact_id,
                        'date': sp_date,
                        'text': text[:80],
                    }
                )

        if not gaps:
            return

        _logger.error(
            'SendPulse Odoo: dialogs-снепшот знайшов %d контакт(ів) з last_inbox_message, '
            'якого немає в sendpulse.message: %s',
            len(gaps),
            gaps,
        )
        lines = '\n'.join(f'• {g["date"]} {g["name"]} — {g["text"]}' for g in gaps[:15])
        more = f'\n... ще {len(gaps) - 15}' if len(gaps) > 15 else ''
        message = (
            f'⚠️ <b>SendPulse: dialogs-снепшот — можлива втрата</b>\n'
            f'{len(gaps)} контакт(ів), де останнє вхідне повідомлення в SendPulse '
            f'не знайдено в Odoo (live-перевірка, незалежно від webhook.data):\n'
            f'{lines}{more}'
        )
        self._notify_telegram(message, silent=False)

    # ── V2 F8: Weekly Telegram funnel report ──────────────────────────────
    @api.model
    def cron_weekly_telegram_report(self):
        """
        Понеділок 09:00 UTC — зводка за минулий тиждень у Telegram-групу.
        No-op якщо weekly_report_enabled=False або Telegram не налаштований.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.weekly_report_enabled', 'False') != 'True':
            return
        if ICP.get_param('odoo_chatwoot_connector.telegram_alerts_enabled', 'False') != 'True':
            _logger.info('SendPulse Odoo: weekly report skipped — Telegram disabled')
            return

        now = fields.Datetime.now()
        week_start = now - timedelta(days=7)
        stats = self._calculate_weekly_stats(week_start, now)
        message = self._format_weekly_report(stats, week_start, now)
        self._notify_telegram(message, silent=False)
        _logger.info('SendPulse Odoo: weekly report sent (%d chars)', len(message))

    @api.model
    def _calculate_weekly_stats(self, period_start, period_end):
        """Збирає метрики за період для tygodniowego report-а."""
        Connect = self.sudo()
        domain_period = [
            ('create_date', '>=', period_start),
            ('create_date', '<', period_end),
        ]
        total = Connect.search_count(domain_period)
        comments = Connect.search_count(domain_period + [('sp_is_comment', '=', True)])
        direct = total - comments

        # Комент-категорії
        cat_counts = {}
        for cat in (
            'question_price',
            'question_dates',
            'question_age',
            'question_general',
            'thanks',
            'complaint',
            'spam',
            'other',
        ):
            cat_counts[cat] = Connect.search_count(
                domain_period + [('sp_is_comment', '=', True), ('sp_comment_category', '=', cat)]
            )

        # Funnel — скільки перейшло до кожної стадії (за період створення)
        funnel = {}
        for stage in (
            'comment_only',
            'private_sent',
            'customer_replied',
            'operator_engaged',
            'lead_created',
            'closed_won',
            'closed_lost',
        ):
            funnel[stage] = Connect.search_count(domain_period + [('sp_funnel_stage', '=', stage)])

        # SLA — медіана часу до першої відповіді
        with_sla = Connect.search(domain_period + [('sp_first_reply_time_sec', '>', 0)])
        sla_values = sorted(with_sla.mapped('sp_first_reply_time_sec'))
        sla_median_sec = sla_values[len(sla_values) // 2] if sla_values else 0
        sla_median_min = sla_median_sec // 60 if sla_median_sec else 0

        # Auto-hide spam за період
        spam_hidden = Connect.search_count(
            domain_period
            + [
                ('sp_comment_category', '=', 'spam'),
                ('sp_replied_public', '=', False),
            ]
        )

        # Leads створені
        Lead = self.env['crm.lead'].sudo()
        leads_created = Lead.search_count(
            [
                ('create_date', '>=', period_start),
                ('create_date', '<', period_end),
                ('id', 'in', Connect.search(domain_period).mapped('sp_lead_id').ids),
            ]
        )

        # Token статуси
        Page = self.env['sendpulse.facebook.page'].sudo()
        bad_tokens = Page.search(
            [
                ('active', '=', True),
                '|',
                ('token_status', 'ilike', 'invalid%'),
                ('token_status', 'ilike', 'expires_soon%'),
            ]
        )

        return {
            'total': total,
            'direct': direct,
            'comments': comments,
            'cat_counts': cat_counts,
            'funnel': funnel,
            'sla_median_min': sla_median_min,
            'spam_hidden': spam_hidden,
            'leads_created': leads_created,
            'bad_tokens': bad_tokens,
        }

    @api.model
    def _format_weekly_report(self, stats, period_start, period_end):
        """HTML-форматований звіт для Telegram."""
        lines = [
            f'📊 <b>Звіт за тиждень {period_start:%d.%m} – {period_end:%d.%m}</b>',
            '',
            f'Нові розмови: <b>{stats["total"]}</b>',
            f'  ├─ Direct DM: {stats["direct"]}',
            f'  └─ Comments: {stats["comments"]}',
            '',
        ]
        if stats['comments']:
            cat = stats['cat_counts']
            lines.append('<b>Категорії коментарів:</b>')
            if cat['question_price']:
                lines.append(f'  💰 Ціна: {cat["question_price"]}')
            if cat['question_dates']:
                lines.append(f'  📅 Терміни: {cat["question_dates"]}')
            if cat['question_age']:
                lines.append(f'  👶 Вік: {cat["question_age"]}')
            if cat['question_general']:
                lines.append(f'  ❓ Загальне: {cat["question_general"]}')
            if cat['thanks']:
                lines.append(f'  🙏 Подяки: {cat["thanks"]}')
            if cat['complaint']:
                lines.append(f'  🚨 Скарги: {cat["complaint"]} (ескаловано)')
            if cat['spam']:
                lines.append(f'  🚫 Спам: {cat["spam"]} (приховано: {stats["spam_hidden"]})')
            if cat['other']:
                lines.append(f'  🔸 Інше: {cat["other"]}')
            lines.append('')

        f = stats['funnel']
        funnel_total = sum(f.values())
        if funnel_total:
            lines.append('<b>Funnel:</b>')
            lines.append(f'  Comment only: {f["comment_only"]}')
            lines.append(f'  Private sent: {f["private_sent"]}')
            lines.append(f'  Customer replied: {f["customer_replied"]}')
            lines.append(f'  Operator engaged: {f["operator_engaged"]}')
            lines.append(f'  Lead created: {f["lead_created"]}')
            if f['closed_won'] or f['closed_lost']:
                lines.append(f'  Closed: won={f["closed_won"]}, lost={f["closed_lost"]}')
            lines.append('')

        if stats['leads_created']:
            lines.append(f'💼 CRM лідів створено: <b>{stats["leads_created"]}</b>')

        if stats['sla_median_min']:
            lines.append(f'⏱ Медіана часу до першої відповіді: <b>{stats["sla_median_min"]} хв</b>')

        if stats['bad_tokens']:
            lines.append('')
            lines.append('⚠️ <b>Проблеми з токенами:</b>')
            for p in stats['bad_tokens']:
                lines.append(f'  • {p.name}: {p.token_status or "?"}')

        # F9 A/B: топ-3 і worst-1 шаблонів за conversion (мін. 10 використань)
        PublicTemplate = self.env['sendpulse.public.template'].sudo()
        significant = PublicTemplate.search(
            [
                ('active', '=', True),
                ('kind', '=', 'standard'),
                ('use_count', '>=', 10),
            ]
        )
        if significant:
            sorted_by_conv = significant.sorted(key='conversion_rate', reverse=True)
            lines.append('')
            lines.append('🏆 <b>Топ шаблонів публічної відповіді:</b>')
            for tpl in sorted_by_conv[:3]:
                lines.append(
                    f'  • {tpl.name}: {tpl.conversion_rate:.1f}% '
                    f'({tpl.customer_replied_count}/{tpl.use_count})'
                )
            if len(sorted_by_conv) > 3:
                worst = sorted_by_conv[-1]
                lines.append(
                    f'  ⚠️ Слабкий: {worst.name}: {worst.conversion_rate:.1f}% '
                    f'({worst.customer_replied_count}/{worst.use_count})'
                )

        return '\n'.join(lines)[:4000]
