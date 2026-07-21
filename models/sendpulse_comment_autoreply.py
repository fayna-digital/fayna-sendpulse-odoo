import hashlib
import logging
from datetime import timedelta

import requests
from markupsafe import Markup, escape
from odoo import api, fields, models

from .sendpulse_connect import _SENDPULSE_INBOUND_LOCK_KEY2

_logger = logging.getLogger(__name__)


class SendpulseConnectCommentAutoreply(models.Model):
    _inherit = 'sendpulse.connect'

    # ════════════════════════════════════════════════════════════════════
    # Коментарі Facebook / Instagram — автовідповідь
    # ════════════════════════════════════════════════════════════════════

    # Ротаційні шаблони публічної відповіді (fallback якщо БД порожня).
    # Основний шлях — sendpulse.public.template (data/sendpulse_public_templates_seed.xml).
    # {name}, {landing_url}, {tg_url} підставляються з runtime.
    _COMMENT_PUBLIC_TEMPLATES = [
        "{name}, дякуємо за коментар! 🏕️\n\nНа жаль, наразі ми не маємо змоги написати вам у приват.\nНапишіть нам сюди у відповідь — ми на зв'язку 24/7 ✨\n\nВся інформація про табори:\n🌐 {landing_url}",
        'Привіт, {name}! 🌟 Дякуємо що написали.\n\nЗараз технічно не виходить відповісти вам у приват —\nтому пишіть нам прямо тут, у коментарях. Відповідаємо цілодобово!\n\nДеталі про програми, дати й вартість 👇\n🌐 {landing_url}',
        '{name}, рада/радий бачити ваше повідомлення! 🏕️✨\n\nНа жаль, написати вам у Messenger зараз не можемо.\nПишіть нам тут — ми онлайн 24/7 і швидко відповімо.\n\nПрограма, безпека, харчування, ціни — все тут:\n🌐 {landing_url}',
        "Дякуємо за інтерес, {name}! 🌲\n\nНа жаль, наша сторінка зараз не може ініціювати приватну розмову.\nЗалиште питання у відповіді на цей коментар — ми на зв'язку без вихідних, 24/7 💬\n\nУся інформація про табори 2026:\n🌐 {landing_url}",
        '{name}, вітаємо! 🏕️\n\nТехнічно не маємо змоги написати вам у приватні повідомлення.\nТож запитуйте сміливо тут — відповідаємо у будь-який час, 24/7! ⚡\n\nУсі деталі про табори — за посиланням:\n🌐 {landing_url}',
        'Привіт, {name}! 💛\n\nДякуємо за коментар. Приватно написати вам, на жаль, не вдається —\nале ми тут поруч у коментарях, відповідаємо цілодобово.\n\nВсе про наші табори (програма / ціни / умови):\n🌐 {landing_url}',
        "{name}, дякуємо що цікавитесь! 🌟\n\nНаразі не маємо технічної можливості написати вам у Messenger.\nПитайте просто тут у коментарі — ми на зв'язку 24/7 і відповімо швидко 🚀\n\nВсе про табори CampScout 2026:\n🌐 {landing_url}",
    ]

    _COMMENT_PUBLIC_REPEAT_TEMPLATE = 'Раді бачити вас знову! 😊 Наш менеджер вже напише вам у повідомленнях — слідкуйте за вхідними 🏕️'

    @api.model
    def _process_comment_event(self, data, contact, bot, service, channel_data_msg):
        """
        Обробляє коментар під постом Facebook/Instagram.
        1. Дедуплікація по comment_id
        2. Знайти/створити sendpulse.connect (sp_is_comment=True)
        3. Публічна відповідь під коментарем (Graph API) — завжди
        4. Приватне повідомлення (Graph API) — тільки якщо перший коментар від контакту
        5. Нотатка оператору у Discuss
        """
        contact_id = contact.get('id', '')
        contact_name = contact.get('name', 'Невідомий')
        channel_data = data.get('info', {}).get('message', {}).get('channel_data', {})
        # FB: comment_id/message; IG via SendPulse: id/text
        comment_id = str(channel_data_msg.get('comment_id') or channel_data_msg.get('id') or '')
        comment_text = channel_data_msg.get('message') or channel_data_msg.get('text') or ''
        post_id = str(
            channel_data_msg.get('post_id')
            or (channel_data_msg.get('media') or {}).get('id')
            or (channel_data.get('media') or {}).get('id')
            or ''
        )
        post_url = (
            (channel_data_msg.get('post') or {}).get('permalink_url')
            or (channel_data.get('media') or {}).get('permalink')
            or ''
        )

        # Перевіряємо чи увімкнена автовідповідь
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.sp_comment_autoreply_enabled', 'True') != 'True':
            _logger.info('SendPulse Odoo: comment autoreply disabled, skipping %s', comment_id)
            return None

        # Multi-page: резолвимо Facebook Page запис з webhook page_id
        page_id_from_payload = str(channel_data_msg.get('page_id') or '')
        Page = self.env['sendpulse.facebook.page'].sudo()
        page = Page.find_by_page_id(page_id_from_payload) if page_id_from_payload else Page.browse()

        # Self-loop guard: не відповідаємо на коментарі від самої Сторінки / IG Business акаунта.
        # Без цього наша публічна відповідь → webhook → нова відповідь → нескінченний цикл.
        from_id = str((channel_data_msg.get('from') or {}).get('id') or '')
        # Збираємо всі свої ID: з webhook + legacy ig_user_id + з усіх активних Page-ів
        own_ids = {x for x in [page_id_from_payload] if x}
        legacy_ig = ICP.get_param('odoo_chatwoot_connector.ig_user_id', '')
        if legacy_ig:
            own_ids.add(legacy_ig)
        for p in Page.search([('active', '=', True)]):
            if p.page_id:
                own_ids.add(p.page_id)
            if p.ig_business_id:
                own_ids.add(p.ig_business_id)
        if from_id and from_id in own_ids:
            _logger.info(
                'SendPulse Odoo: self-comment detected (from=%s == own), skipping %s',
                from_id,
                comment_id,
            )
            return None

        # Race-guard: advisory lock на comment_id — якщо той самий webhook
        # прийде двічі одночасно (SendPulse іноді ретраїть), другий чекає.
        if comment_id:
            lock_key1 = (
                int(hashlib.md5(f'comment|{comment_id}'.encode()).hexdigest()[:8], 16) & 0x7FFFFFFF
            )
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(%s, %s)',
                (lock_key1, _SENDPULSE_INBOUND_LOCK_KEY2),
            )

        # Дедуплікація: той самий comment_id вже оброблявся
        if comment_id:
            existing = self.search([('sp_comment_id', '=', comment_id)], limit=1)
            if existing:
                _logger.info('SendPulse Odoo: comment %s already processed, skipping', comment_id)
                return existing

        # Знаходимо/створюємо розмову
        connect = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
                ('sp_is_comment', '=', True),
            ],
            limit=1,
        )

        now = fields.Datetime.now()
        if not connect:
            connect = self.create(
                {
                    'name': contact_name,
                    'sendpulse_contact_id': contact_id,
                    'service': service,
                    'bot_id': bot.get('id', ''),
                    'bot_name': bot.get('name', ''),
                    'stage': 'new',
                    'sp_is_comment': True,
                    'sp_comment_id': comment_id,
                    'sp_comment_text': comment_text[:500] if comment_text else '',
                    'sp_post_id': post_id,
                    'sp_post_url': post_url,
                    'sp_page_id': page_id_from_payload or (page.page_id if page else ''),
                    'last_message_preview': f'💬 Коментар: {comment_text[:80]}'
                    if comment_text
                    else '💬 Коментар',
                    'last_message_date': now,
                    'sp_funnel_stage': 'comment_only',
                }
            )
        else:
            connect.write(
                {
                    'sp_comment_id': comment_id,
                    'sp_comment_text': comment_text[:500] if comment_text else '',
                    'sp_post_id': post_id,
                    'sp_post_url': post_url,
                    'sp_page_id': page_id_from_payload or connect.sp_page_id,
                    'last_message_preview': f'💬 Коментар: {comment_text[:80]}'
                    if comment_text
                    else '💬 Коментар',
                    'last_message_date': now,
                }
            )

        if not connect.channel_id:
            connect._create_discuss_channel()

        # LLM-класифікація коментаря (якщо увімкнено)
        category = self._classify_comment(comment_text, service)
        connect.write({'sp_comment_category': category})
        _logger.info('SendPulse Odoo: comment %s classified as "%s"', comment_id, category)

        # Визначаємо чи надсилати приватне (тільки перший раз для цього контакту)
        already_private = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('sp_replied_private', '=', True),
            ],
            limit=1,
        )
        # Не спамимо людей у яких вже є прямий діалог (не comment)
        has_direct_dialog = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('sp_is_comment', '=', False),
            ],
            limit=1,
        )
        send_private = (
            not bool(already_private)
            and not bool(has_direct_dialog)
            and ICP.get_param('odoo_chatwoot_connector.sp_comment_private_enabled', 'True')
            == 'True'
        )

        send_public = (
            ICP.get_param('odoo_chatwoot_connector.sp_comment_public_enabled', 'True') == 'True'
        )

        # Маршрутизація за категорією (якщо класифікатор увімкнено і дав результат != 'other'):
        # - thanks / spam: не відповідаємо взагалі (автовідповідь на подяку виглядає бот-подібно)
        # - complaint: не автовідповідь, лише нотатка оператору з мітою 🚨 (ескалація)
        # - question_*: поточна логіка (публічна + приватна) — без змін
        if category in ('thanks', 'spam'):
            _logger.info(
                'SendPulse Odoo: category=%s → skip auto-reply for %s', category, comment_id
            )
            send_public = False
            send_private = False
            # Для spam — приховуємо коментар через Graph API (якщо увімкнено)
            if (
                category == 'spam'
                and ICP.get_param('odoo_chatwoot_connector.sp_comment_hide_spam_enabled', 'True')
                == 'True'
                and comment_id
            ):
                hide_ok, hide_err = connect._hide_comment(comment_id, service, page=page)
                if hide_ok:
                    _logger.info('SendPulse Odoo: spam comment %s hidden', comment_id)
                    self._notify_telegram(
                        f'🚫 <b>Спам приховано</b>\n'
                        f'Клієнт: {contact_name}\n'
                        f'Текст: <i>{(comment_text or "")[:200]}</i>\n'
                        f'{post_url}',
                        silent=True,
                    )
                else:
                    _logger.warning(
                        'SendPulse Odoo: failed to hide spam %s: %s', comment_id, hide_err
                    )
        elif category == 'complaint':
            _logger.warning(
                'SendPulse Odoo: complaint detected → escalation, no auto-reply for %s', comment_id
            )
            send_public = False
            send_private = False
            self._notify_telegram(
                f'🚨 <b>СКАРГА під постом</b> — потрібна увага!\n\n'
                f'👤 Клієнт: <b>{contact_name}</b>\n'
                f'📝 Текст: <i>{(comment_text or "")[:500]}</i>\n\n'
                f'🔗 Допис: {post_url or "—"}'
            )

        # Тексти з підстановкою URL (per-page override → глобальний ICP → дефолт)
        landing_url = (page.landing_url if page else '') or ICP.get_param(
            'odoo_chatwoot_connector.sp_comment_landing_url', 'https://lato2026.campscout.eu'
        )
        tg_url = (page.tg_url if page else '') or ICP.get_param(
            'odoo_chatwoot_connector.sp_comment_tg_url', 'https://t.me/campscouting'
        )

        # Публічна відповідь
        public_ok = False
        public_error = None
        if send_public and comment_id:
            # Ім'я для звертання у шаблоні. SendPulse webhook кладе FB profile name
            # у contact.name; коли пусто або default — використовуємо нейтральне.
            display_name = contact_name if contact_name and contact_name != 'Невідомий' else 'друже'
            # F9: Вибір шаблону через модель sendpulse.public.template (epsilon-greedy).
            # Fallback на hard-coded константи якщо модель порожня (міграція не
            # виконана або всі шаблони деактивовано).
            PublicTemplate = self.env['sendpulse.public.template'].sudo()
            template = PublicTemplate.pick_template(is_repeat=bool(already_private))
            if template:
                public_text = template.text.format(
                    name=display_name,
                    landing_url=landing_url or 'https://lato2026.campscout.eu',
                    tg_url=tg_url or 'https://t.me/campscouting',
                )
            elif bool(already_private):
                public_text = self._COMMENT_PUBLIC_REPEAT_TEMPLATE
            else:
                # Fallback: старий round-robin по константах
                if post_id:
                    count = self.search_count(
                        [
                            ('sp_is_comment', '=', True),
                            ('sp_post_id', '=', post_id),
                            ('sp_replied_public', '=', True),
                        ]
                    )
                else:
                    count = self.search_count([('sp_is_comment', '=', True)])
                tmpl = self._COMMENT_PUBLIC_TEMPLATES[count % len(self._COMMENT_PUBLIC_TEMPLATES)]
                public_text = tmpl.format(
                    name=display_name,
                    landing_url=landing_url or 'https://lato2026.campscout.eu',
                    tg_url=tg_url or 'https://t.me/campscouting',
                )
            public_ok, public_error = connect._send_comment_public_reply(
                comment_id, service, public_text, page=page
            )
            if public_ok:
                vals = {'sp_replied_public': True}
                if template:
                    vals['sp_public_template_id'] = template.id
                connect.write(vals)
                if template:
                    template.bump_use()

        # Приватне повідомлення
        private_ok = False
        private_error = None
        if send_private and comment_id:
            yt_url = ICP.get_param(
                'odoo_chatwoot_connector.sp_comment_yt_url',
                'https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV',
            )
            private_text_tmpl = ICP.get_param(
                'odoo_chatwoot_connector.sp_comment_private_text',
                '',
            )
            if not private_text_tmpl:
                private_text_tmpl = (
                    'Вітаємо! 🏕️ Дякуємо за ваш коментар під нашим постом.\n\n'
                    'Підготували для вас відповіді на найпоширеніші запитання — '
                    'безпека, програма, харчування, вартість, терміни:\n'
                    '🎬 {yt_url}\n\n'
                    'Вся актуальна інформація про табори 2026 також тут:\n'
                    '🌐 {landing_url}\n\n'
                    'Якщо залишились питання — пишіть тут, відповімо особисто! 😊'
                )
            private_text = private_text_tmpl.format(
                landing_url=landing_url or 'https://lato2026.campscout.eu',
                tg_url=tg_url or 'https://t.me/campscouting',
                yt_url=yt_url
                or 'https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV',
            )
            private_ok, private_error = connect._send_comment_private_reply(
                comment_id, private_text, service, page=page
            )
            if private_ok:
                connect.write(
                    {
                        'sp_replied_private': True,
                        'sp_messenger_window_expires_at': fields.Datetime.now()
                        + timedelta(hours=24),
                        'sp_window_alert_sent': False,
                        'sp_funnel_stage': 'private_sent',
                    }
                )

        # Нотатка оператору
        connect._notify_operator_comment(
            contact_name=contact_name,
            comment_text=comment_text,
            post_url=post_url,
            sent_public=public_ok,
            sent_private=private_ok,
            public_error=public_error,
            private_error=private_error,
            category=category,
        )

        return connect

    _COMMENT_CATEGORIES = (
        'question_price',
        'question_dates',
        'question_age',
        'question_general',
        'thanks',
        'complaint',
        'spam',
        'other',
    )

    def _classify_comment(self, text, service='facebook'):
        """
        Класифікує коментар через Anthropic Claude API.
        Повертає одну з _COMMENT_CATEGORIES. Фолбек 'other' якщо LLM вимкнено/помилка.
        """
        if not text or not text.strip():
            return 'other'
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.llm_classifier_enabled', 'False') != 'True':
            return 'other'
        api_key = ICP.get_param('odoo_chatwoot_connector.anthropic_api_key', '')
        if not api_key:
            return 'other'
        model = ICP.get_param('odoo_chatwoot_connector.llm_model', 'claude-haiku-4-5')

        prompt = (
            'Класифікуй коментар під постом літнього дитячого табору CampScout в одну з категорій:\n'
            '- question_price (питання про ціну, вартість, знижки)\n'
            '- question_dates (питання про терміни, дати заїздів, коли)\n'
            '- question_age (питання про вік дітей, з якого віку)\n'
            '- question_general (інше питання: програма, харчування, безпека, місце, документи)\n'
            '- thanks (подяка, позитивні емодзі без питання, лайк)\n'
            '- complaint (скарга, негатив, претензія)\n'
            '- spam (спам, реклама, шкідливе посилання, провокація)\n'
            '- other (не вдалось класифікувати)\n\n'
            f'Коментар: "{text[:400]}"\n\n'
            'Відповідай ОДНИМ СЛОВОМ — назвою категорії без пояснень.'
        )
        try:
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type': 'application/json',
                },
                json={
                    'model': model,
                    'max_tokens': 20,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=10,
            )
            if resp.status_code != 200:
                _logger.warning(
                    'SendPulse Odoo: LLM classifier HTTP %d — %s',
                    resp.status_code,
                    resp.text[:200],
                )
                return 'other'
            data = resp.json()
            raw = (data.get('content') or [{}])[0].get('text', '').strip().lower()
            for valid in self._COMMENT_CATEGORIES:
                if valid in raw:
                    return valid
            _logger.info('SendPulse Odoo: LLM returned unknown category "%s"', raw)
            return 'other'
        except Exception as e:
            _logger.warning('SendPulse Odoo: LLM classifier exception — %s', e)
            return 'other'

    # ── V2 F7: Bulk-archive old closed comment records ────────────────────
    @api.model
    def cron_archive_old_comment_records(self):
        """
        Раз/місяць. Soft-archive (active=False) для sp_is_comment=True записів
        у stage=close старших за auto_archive_comments_days днів. Залишає у БД
        для історії, але прибирає з default views.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if (
            ICP.get_param('odoo_chatwoot_connector.auto_archive_comments_enabled', 'False')
            != 'True'
        ):
            return
        try:
            days = int(ICP.get_param('odoo_chatwoot_connector.auto_archive_comments_days', '30'))
        except (ValueError, TypeError):
            days = 30
        threshold = fields.Datetime.now() - timedelta(days=days)
        candidates = self.search(
            [
                ('sp_is_comment', '=', True),
                ('stage', '=', 'close'),
                ('active', '=', True),
                ('write_date', '<', threshold),
            ]
        )
        if candidates:
            candidates.write({'active': False})
        _logger.info(
            'SendPulse Odoo: cron_archive_old_comment_records — archived %d',
            len(candidates),
        )

    _CATEGORY_LABELS = {
        'question_price': '💰 Питання про ціну',
        'question_dates': '📅 Питання про терміни',
        'question_age': '👶 Питання про вік',
        'question_general': '❓ Загальне питання',
        'thanks': '🙏 Подяка / позитив',
        'complaint': '🚨 СКАРГА — потрібна увага оператора',
        'spam': '🚫 Спам',
        'other': '🔸 Інше',
    }

    def _notify_operator_comment(
        self,
        contact_name,
        comment_text,
        post_url,
        sent_public,
        sent_private,
        public_error,
        private_error,
        category=None,
    ):
        """Надсилає системну нотатку від OdooBot у Discuss-канал розмови."""
        if not self.channel_id:
            return

        lines = [f'💬 Новий коментар під постом [{self._get_service_label()}]', '']
        lines.append(f'👤 Клієнт: {contact_name}')
        if comment_text:
            lines.append(f'📝 Коментар: "{comment_text}"')
        if category and category != 'other':
            lines.append(f'🏷️ Категорія: {self._CATEGORY_LABELS.get(category, category)}')
        if post_url:
            lines.append(f'🔗 Допис: {post_url}')
        lines.append('')

        if sent_public:
            lines.append('✅ Публічна відповідь опублікована під коментарем')
        elif public_error:
            lines.append(f'❌ Публічна відповідь не надіслана: {public_error}')
        else:
            lines.append('⏭️ Публічна відповідь вимкнена в налаштуваннях')

        if sent_private:
            lines.append('✅ Приватне повідомлення надіслано у Messenger')
            lines.append(
                '⏳ Очікуємо відповіді від клієнта — поки клієнт не відповів, писати йому не можна (правило Meta)'
            )
        elif private_error:
            lines.append(f'❌ Приватне повідомлення не надіслано: {private_error}')
        else:
            lines.append(
                '⏭️ Приватне повідомлення не надіслається (клієнт вже отримував раніше або вимкнено)'
            )

        body = Markup('<br/>').join(escape(line) if line else Markup('') for line in lines)
        self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
            author_id=self.env.ref('base.partner_root').id,
        )

