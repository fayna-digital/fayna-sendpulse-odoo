import logging
from datetime import timedelta

import requests
from markupsafe import Markup, escape
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SendpulseConnectAiAssist(models.Model):
    _inherit = 'sendpulse.connect'

    # ── Magic-number константи (аудит 19.07.2026, issue #8) ───────────────
    _ANTHROPIC_API_TIMEOUT = 15  # requests timeout(s) для викликів Claude API
    _LOG_TEXT_PREVIEW_LEN = 200  # обрізка resp.text/raw у _logger.warning
    _LOG_RAW_JSON_PREVIEW_LEN = 500  # обрізка більшого RAW JSON-фрагменту (parse fail)
    _EXCEPTION_MSG_PREVIEW_LEN = 100  # обрізка str(e) у reason-полях
    _RAG_QUESTION_PROMPT_MAX_LEN = 500  # ліміт question_text у RAG-промпті
    _RAG_QUESTION_NOTE_PREVIEW_LEN = 200  # ліміт question_text у Discuss-нотатці
    _RAG_AUTO_ANSWER_RATE_LIMIT_HOURS = 1  # rate-limit авто-відповіді RAG (1x/год)

    # ── V2 F14: Live event seats context для AI prompts ──────────────────
    def _get_live_events_context(self, limit=15, low_ratio=0.3):
        """
        Повертає текстовий блок активних майбутніх event.event з їх
        live `seats_available` — щоб AI у F10 suggestions і F1 RAG знав
        які табори скільки мають вільних місць. Позначає 🔴 повні і
        ❗ майже повні (<low_ratio від seats_max) для FOMO.

        Повертає '' якщо feature-flag вимкнений, ORM помилка або немає
        активних подій.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.event_seats_awareness_enabled', 'True') != 'True':
            return ''
        from datetime import datetime

        try:
            events = (
                self.env['event.event']
                .sudo()
                .search(
                    [
                        ('active', '=', True),
                        ('date_begin', '>', datetime.now()),
                        ('stage_id.pipe_end', '=', False),
                    ],
                    order='date_begin',
                    limit=limit,
                )
            )
        except Exception as e:
            _logger.warning('SendPulse Odoo: F14 events query failed — %s', e)
            return ''
        lines = []
        for ev in events:
            name = (ev.name or '').strip()
            if not name:
                continue
            date_s = ev.date_begin.strftime('%d.%m') if ev.date_begin else '?'
            if ev.seats_limited and ev.seats_max:
                avail = ev.seats_available or 0
                if avail <= 0:
                    status = '🔴 ПОВНИЙ'
                elif avail / ev.seats_max <= low_ratio:
                    status = f'❗ {avail}/{ev.seats_max} (майже повний!)'
                else:
                    status = f'{avail}/{ev.seats_max} місць'
            else:
                status = 'без ліміту місць'
            lines.append(f'• {date_s} — {name[:70]} — {status}')
        if not lines:
            return ''
        return (
            'LIVE ТАБОРИ 2026 (з Odoo, seats_available АКТУАЛЬНО ЗАРАЗ '
            '— рекомендуй лише ті, де є місця; ❗ = FOMO, 🔴 = запропонуй аналог):\n'
            + '\n'.join(lines)
        )

    # ── V2 F10: Suggested reply drafts для оператора ──────────────────────
    def _generate_reply_suggestions(self, count=3):
        """
        Через Claude генерує N варіантів наступної відповіді оператора
        на основі контексту розмови. Returns list of strings.

        Для OWL-компонента у Discuss side-panel. Toggle: `suggested_reply_enabled`.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.suggested_reply_enabled', 'False') != 'True':
            return []
        api_key = ICP.get_param('odoo_chatwoot_connector.anthropic_api_key', '')
        if not api_key:
            return []
        model = ICP.get_param('odoo_chatwoot_connector.llm_model', 'claude-haiku-4-5')

        # Контекст: останні 10 повідомлень обох сторін, хронологічно
        recent = self.message_ids.sorted('date', reverse=False)[-10:]
        history_lines = []
        for m in recent:
            who = '👤 Клієнт' if m.direction == 'incoming' else '🧑 Оператор'
            text = (m.text_message or '').strip().replace('\n', ' ')[:300]
            if text:
                history_lines.append(f'{who}: {text}')
        history = '\n'.join(history_lines) or '(порожньо — оператор ще не писав)'

        # F12: Спроба виявити email у останніх повідомленнях клієнта
        # і linkувати partner (ідемпотентно — якщо вже є sp_booking_email, skip).
        if not self.sp_booking_email:
            self._try_extract_email_and_link()

        # Контекст профілю (базовий)
        profile_parts = [f"Ім'я клієнта: {self.name or '—'}"]
        if self.sp_child_name:
            profile_parts.append(f'Дитина (з бота): {self.sp_child_name}')
        if self.sp_booking_email:
            profile_parts.append(f'Email: {self.sp_booking_email}')
        if self.social_username:
            profile_parts.append(f'Username: @{self.social_username}')
        profile_parts.append(f'Канал: {self._get_service_label()}')

        # F12: Розширений контекст — якщо є linked partner
        partner = self.partner_id
        if partner:
            profile_parts.append('')
            profile_parts.append('── ІДЕНТИФІКОВАНИЙ КЛІЄНТ ──')
            profile_parts.append(
                f'Partner ID: {partner.id}, створено: {partner.create_date.strftime("%Y-%m-%d") if partner.create_date else "—"}'
            )
            if partner.email and partner.email != self.sp_booking_email:
                profile_parts.append(f'Email у партнера: {partner.email}')
            if partner.phone or partner.mobile:
                profile_parts.append(f'Телефон: {partner.phone or partner.mobile}')
            if partner.city or partner.street:
                addr = ', '.join(filter(None, [partner.street, partner.city]))
                profile_parts.append(f'Адреса: {addr}')

            # crm.lead контекст — відкриті + останні закриті
            leads = (
                self.env['crm.lead']
                .sudo()
                .search(
                    [('partner_id', '=', partner.id)],
                    order='create_date desc',
                    limit=5,
                )
            )
            if leads:
                profile_parts.append('')
                profile_parts.append('CRM-ліди (останні):')
                for lead in leads:
                    stage = lead.stage_id.name if lead.stage_id else '—'
                    date = lead.create_date.strftime('%Y-%m-%d') if lead.create_date else '—'
                    probab = f'{lead.probability:.0f}%' if lead.probability else '—'
                    profile_parts.append(
                        f'  • [{date}] {lead.name or "—"} — stage: {stage}, prob: {probab}'
                    )

            # sale.order історія
            orders = (
                self.env['sale.order']
                .sudo()
                .search(
                    [('partner_id', '=', partner.id), ('state', 'in', ('sale', 'done'))],
                    order='date_order desc',
                    limit=3,
                )
            )
            if orders:
                profile_parts.append('')
                profile_parts.append('Історія замовлень:')
                for o in orders:
                    date = o.date_order.strftime('%Y-%m-%d') if o.date_order else '—'
                    amount = f'{o.amount_total:.0f} {o.currency_id.name or ""}'.strip()
                    profile_parts.append(f'  • [{date}] {o.name} — {amount}')
        else:
            profile_parts.append('')
            profile_parts.append('⚠️ КЛІЄНТ НЕ ІДЕНТИФІКОВАНИЙ — email невідомий')

        profile = '\n'.join(profile_parts)

        # F14: live seats у активних подіях — AI має знати реальну доступність
        live_events = self._get_live_events_context()
        live_events_block = f'{live_events}\n\n' if live_events else ''

        prompt = (
            f'Ти — AI-асистент менеджера CampScout (дитячі табори у Польщі).\n\n'
            f'{live_events_block}'
            f'КАНОНІЧНІ ФАКТИ (НЕ ВИГАДУВАТИ НІЧОГО ІНШОГО!):\n'
            f'• Флагмани 2026: TDK 6-11р 3 300 zł (10 днів), Дослідники морів 7-17р 3 500 zł (14 днів), '
            f'Пошумимо 12-17р 3 250 zł (14 днів)\n'
            f'• Промо-ціни ДО 01.05.2026, після +300 zł\n'
            f'• Швейцарія: 5 500 zł, страхівка+медик+дорога окремо. Франція/Італія/Іспанія 2026 — продано\n'
            f'• У польські табори входить: проживання, 4-разове харчування, програма, NNW, медик 24/7\n'
            f"• Бронь: оплата частинами або повна, за 14 днів до старту все закрите. М'яка бронь 48h без оплати\n"
            f'• Трансфер окрема послуга: 50 zł пункт збору+автобус, або індивідуальний супровід\n'
            f'• Телефони здаємо у сейф, щовечора 30хв дзвінки (крім Вовча Стежа/Цивілізація — раз на 3д)\n'
            f'• Безпека: Ustawa Kamilka + KRK, Compensa VIG 31 617 PLN, ліцензія №1129\n'
            f'• Соц-доказ: 3 сезони, 1 500+ дітей, 4.9/5 (200+ відгуків Google/FB)\n'
            f'• -5% за TG-канал: https://t.me/campscouting. Landing: https://lato2026.campscout.eu\n\n'
            f"ПРОЦЕДУРА ОФОРМЛЕННЯ (ОБОВ'ЯЗКОВО знати + пояснювати клієнту!):\n"
            f'• Дані ДИТИНИ (ПІБ, дата народження, медичні особливості, діагнози, алергії, '
            f"контакти для екстреного зв'язку) батьки заповнюють САМІ у кваліфікаційній "
            f'(табірній) картці в особистому кабінеті на сайті — це додаток №5 до Договору.\n'
            f'• ЮРИДИЧНА ПРИЧИНА: після заповнення батьки ПІДПИСУЮТЬ картку — цим вони '
            f'беруть юридичну відповідальність за достовірність даних. Ми як оператори '
            f'НЕ МАЄМО ПРАВА записувати ці дані за батьків у чаті — без їхнього підпису '
            f'картка юридичної сили не має, і дані не можуть бути використані.\n'
            f'• Тому у чаті ми ніколи не питаємо ПІБ/дату народження/медичні дані дитини. '
            f'Якщо клієнт сам пропонує — ввічливо просимо ввести у картці в панелі клієнта.\n'
            f'• У чаті з батьками питаємо ЇХНІ дані (якщо потрібно для консультації): '
            f'ПІБ замовника, адреса проживання, телефон, email.\n'
            f'• Для бронювання — відправляємо у особистий кабінет, там батьки самі заповнюють '
            f'картку Учасника, підписують, отримують рахунок, роблять оплату.\n\n'
            f'Прочитай історію і запропонуй {count} РІЗНИХ варіантів наступної відповіді.\n\n'
            f'Контекст клієнта:\n{profile}\n\n'
            f'Історія (останнє повідомлення клієнта внизу):\n{history}\n\n'
            f"Стиль (ОБОВ'ЯЗКОВО!):\n"
            f'• Звертання — ТІЛЬКИ на «Ви» (ніколи «ти/тобі/твій»). Батьки — дорослі люди, '
            f'ми продавець-консультант, не ровесники.\n'
            f'• 2-5 речень, по-людському, не формально\n'
            f'• Без клішe («Дякуємо за запитання»)\n'
            f'• Емодзі 1-2 максимум\n'
            f'• Варіанти РІЗНІ за підходом (інформативний / уточнюючий / емпатичний)\n'
            f"• Ім'я клієнта у першій фразі якщо відоме\n"
            f'• Закінчуй CTA-запитанням якщо доречно\n'
            f'• Якщо клієнт НЕ ІДЕНТИФІКОВАНИЙ (позначка у профілі ⚠️) і цікавиться '
            f'деталями/ціною/програмою — ОДИН з варіантів може ввічливо запропонувати '
            f"залишити email для особистої пропозиції (не нав'язливо, природно у контексті).\n"
            f'• Якщо клієнт ІДЕНТИФІКОВАНИЙ (є partner/ліди/замовлення) — використай контекст '
            f'(минулі табори, стадія ліда) для персоналізації, але не цитуй деталі буквально.\n'
            f'• Якщо клієнт питає про КОНКРЕТНИЙ табір/зміну — перевір LIVE ТАБОРИ вище: '
            f'❗ <30% → створи FOMO («Ірине, лишилось тільки 5 місць, радимо не тягнути»); '
            f'🔴 повний → ЧЕСНО скажи і запропонуй аналог з вільними місцями; '
            f'звичайний → не акцентуй на seats без потреби.\n\n'
            f'КАТЕГОРИЧНО ЗАБОРОНЕНО:\n'
            f'❌ Звертання на «ти» — завжди «Ви», «Вам», «Ваш», «Ваша дитина»\n'
            f'❌ Просити у чаті ПІБ дитини, дату народження, медичні дані/діагнози/алергії — '
            f'все це заповнюється батьками у кваліфікаційній картці у панелі клієнта\n'
            f'❌ Писати «надішли документи», «заповни анкету у чаті» — відправляємо у особистий кабінет\n'
            f'❌ Вигадувати ціни, дати, табори, факти яких немає у КАНОНІЧНИХ ФАКТАХ\n'
            f'❌ Слово «доставка» про дітей (тільки «трансфер», «привезти»)\n'
            f'❌ «11 років перехідний вік» (для 11 є TDK від 6)\n'
            f'❌ Агресивно порівнювати з конкурентами\n\n'
            f'Формат — STRICT JSON:\n'
            f'{{"suggestions": ["варіант 1", "варіант 2", "варіант 3"]}}\n'
            f'Поверни ЛИШЕ JSON без пояснень.'
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
                    'max_tokens': 800,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=self._ANTHROPIC_API_TIMEOUT,
            )
            if resp.status_code != 200:
                _logger.warning(
                    'SendPulse Odoo: suggested_reply HTTP %d — %s',
                    resp.status_code,
                    resp.text[: self._LOG_TEXT_PREVIEW_LEN],
                )
                return []
            raw = (resp.json().get('content') or [{}])[0].get('text', '').strip()
            import json as _json
            import re as _re

            # Strip ```json / ``` code fences Claude любить додавати
            cleaned = _re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=_re.MULTILINE).strip()
            data = None
            try:
                data = _json.loads(cleaned)
            except Exception:
                # Balanced-brace extraction (не non-greedy, щоб не обривало на вкладених)
                start = cleaned.find('{')
                if start >= 0:
                    depth = 0
                    for i, ch in enumerate(cleaned[start:], start=start):
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                try:
                                    data = _json.loads(cleaned[start : i + 1])
                                except Exception:
                                    pass
                                break
            if not isinstance(data, dict):
                _logger.warning(
                    'SendPulse Odoo: suggested_reply failed to parse JSON. RAW=%s',
                    raw[: self._LOG_RAW_JSON_PREVIEW_LEN],
                )
                return []
            suggestions = data.get('suggestions') or []
            if not suggestions:
                _logger.info(
                    'SendPulse Odoo: suggested_reply — LLM повернув 0 варіантів. RAW=%s',
                    raw[:300],
                )
            # Filter: only non-empty strings, max N
            return [s.strip() for s in suggestions if isinstance(s, str) and s.strip()][:count]
        except Exception as e:
            _logger.warning('SendPulse Odoo: suggested_reply exception — %s', e)
            return []

    @api.model
    def suggested_reply_for_channel(self, channel_id, count=3):
        """RPC endpoint — для OWL-компонента. Бере connect за channel_id."""
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect:
            return []
        return connect._generate_reply_suggestions(count=count)

    # ── V2 F12: Email extraction + partner identification ────────────────
    _EMAIL_REGEX = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    def _try_extract_email_and_link(self):
        """
        Сканує останні 20 incoming повідомлень на email (regex), бере перший.
        Якщо знайшов: set sp_booking_email + спроба link partner_id через
        існуючий _find_partner. Ідемпотентно — якщо sp_booking_email уже
        встановлений, no-op.
        """
        self.ensure_one()
        if self.sp_booking_email:
            return False
        import re as _re

        recent = self.message_ids.filtered(
            lambda m: m.direction == 'incoming' and (m.text_message or '').strip()
        ).sorted('date', reverse=True)[:20]
        for msg in recent:
            m = _re.search(self._EMAIL_REGEX, msg.text_message or '')
            if not m:
                continue
            email = m.group(0).lower().strip()
            vals = {'sp_booking_email': email}
            if not self.partner_id:
                partner = self.env['res.partner'].search([('email', '=ilike', email)], limit=1)
                if partner:
                    vals['partner_id'] = partner.id
                    if self.sendpulse_contact_id and not partner.sendpulse_contact_id:
                        partner.write({'sendpulse_contact_id': self.sendpulse_contact_id})
            self.write(vals)
            _logger.info(
                'SendPulse Odoo: F12 email extracted %s from connect %s, linked partner=%s',
                email,
                self.id,
                vals.get('partner_id'),
            )
            return True
        return False

    # ── V2 F11: Auto-translate UA↔PL через Claude ────────────────────────
    def _translate_text(self, text, target_lang='pl'):
        """
        Перекладає текст на target_lang через Claude. Повертає dict:
        {translated: str, source_lang: str, error: str or None}.
        No-op якщо toggle вимкнено або API key відсутній.
        """
        if not text or not text.strip():
            return {'translated': '', 'source_lang': '', 'error': 'empty_input'}
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.auto_translate_enabled', 'False') != 'True':
            return {'translated': '', 'source_lang': '', 'error': 'disabled'}
        api_key = ICP.get_param('odoo_chatwoot_connector.anthropic_api_key', '')
        if not api_key:
            return {'translated': '', 'source_lang': '', 'error': 'no_api_key'}

        model = ICP.get_param('odoo_chatwoot_connector.llm_model', 'claude-haiku-4-5')
        target_full = {
            'pl': 'польську',
            'uk': 'українську',
            'en': 'англійську',
            'ru': 'російську',
        }.get(target_lang, target_lang)
        prompt = (
            f'Визнач мову вхідного тексту і переклади його на {target_full}.\n'
            f'Якщо текст уже на цільовій мові — поверни його без змін.\n'
            f'Стиль розмовний, природній (клієнтсько-операторський чат).\n'
            f'Зберігай емодзі, URL, цифри, імена власні.\n\n'
            f'Вхідний текст:\n"""\n{text[:2000]}\n"""\n\n'
            f'Формат — STRICT JSON:\n'
            f'{{"source_lang": "uk|pl|en|ru|...", "translated": "переклад"}}\n'
            f'Поверни ТІЛЬКИ JSON без пояснень.'
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
                    'max_tokens': 2000,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=self._ANTHROPIC_API_TIMEOUT,
            )
            if resp.status_code != 200:
                _logger.warning(
                    'SendPulse Odoo: translate HTTP %d — %s',
                    resp.status_code,
                    resp.text[: self._LOG_TEXT_PREVIEW_LEN],
                )
                return {'translated': '', 'source_lang': '', 'error': f'http_{resp.status_code}'}
            raw = (resp.json().get('content') or [{}])[0].get('text', '').strip()
            import json as _json
            import re as _re

            cleaned = _re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=_re.MULTILINE).strip()
            data = None
            try:
                data = _json.loads(cleaned)
            except Exception:
                start = cleaned.find('{')
                if start >= 0:
                    depth = 0
                    for i, ch in enumerate(cleaned[start:], start=start):
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                try:
                                    data = _json.loads(cleaned[start : i + 1])
                                except Exception:
                                    pass
                                break
            if not isinstance(data, dict):
                _logger.warning('SendPulse Odoo: translate parse failed. RAW=%s', raw[:300])
                return {'translated': '', 'source_lang': '', 'error': 'parse_failed'}
            return {
                'translated': (data.get('translated') or '').strip(),
                'source_lang': (data.get('source_lang') or '').strip().lower(),
                'error': None,
            }
        except Exception as e:
            _logger.warning('SendPulse Odoo: translate exception — %s', e)
            return {'translated': '', 'source_lang': '', 'error': f'exception:{e}'}

    @api.model
    def translate_last_inbound_for_channel(self, channel_id, target_lang='pl'):
        """
        RPC для OWL-панелі. Перекладає останнє incoming повідомлення у
        channel на target_lang. Повертає {'translated', 'source_lang',
        'original', 'error'}.
        """
        empty = {'translated': '', 'source_lang': '', 'original': '', 'error': None}
        connect = self.search([('channel_id', '=', channel_id)], limit=1)
        if not connect:
            return {**empty, 'error': 'no_connect'}
        last_in = connect.message_ids.filtered(
            lambda m: m.direction == 'incoming' and (m.text_message or '').strip()
        ).sorted('date', reverse=True)[:1]
        if not last_in:
            return {**empty, 'error': 'no_inbound'}
        text = (last_in.text_message or '').strip()
        result = connect._translate_text(text, target_lang=target_lang)
        return {
            'translated': result['translated'],
            'source_lang': result['source_lang'],
            'original': text[:2000],
            'error': result['error'],
        }

    # ── V2 F1: RAG FAQ auto-answer ────────────────────────────────────────
    def _rag_answer_question(self, question_text, contact_name=''):
        """
        Через Anthropic Claude підбирає найкращу FAQ відповідь на питання клієнта
        і персоналізує її. Модель читає список всіх активних FAQ у контексті
        (не embedding-based, а in-context retrieval — простіше і достатньо для <100 FAQ).

        Повертає dict:
        {
            'matched': bool,
            'faq_id': int or None,
            'confidence': float (0..1),
            'answer': str,
            'reason': str (для debug),
        }

        No-op повертає {'matched': False, ...} якщо RAG вимкнений або API key відсутній.
        """
        empty = {
            'matched': False,
            'faq_id': None,
            'confidence': 0.0,
            'answer': '',
            'reason': 'not_configured',
        }
        if not question_text or not question_text.strip():
            return empty

        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.rag_auto_answer_enabled', 'False') != 'True':
            return empty
        api_key = ICP.get_param('odoo_chatwoot_connector.anthropic_api_key', '')
        if not api_key:
            return {**empty, 'reason': 'no_api_key'}

        Faq = self.env['sendpulse.faq.entry'].sudo()
        faqs = Faq.get_active_faq_for_prompt()
        if not faqs:
            return {**empty, 'reason': 'no_faqs'}

        model = ICP.get_param('odoo_chatwoot_connector.llm_model', 'claude-haiku-4-5')

        # Будуємо prompt з переліком FAQ у компактному форматі
        faq_block = '\n'.join(
            [f'FAQ_{f["id"]}: Q: {f["question"]}\n   A: {f["answer"]}' for f in faqs]
        )
        contact_hint = f' Клієнт: {contact_name}.' if contact_name else ''
        # F14: live seats якщо питання стосується конкретного табору
        live_events = self._get_live_events_context()
        live_events_block = f'{live_events}\n\n' if live_events else ''
        prompt = (
            f'Ти — AI-асистент менеджера CampScout (дитячі табори 6-17 років у Польщі).\n'
            f'Наш стиль: продавці-консультанти, не сухі факти — ЦІННІСТЬ + ТЕРМІНОВІСТЬ + CTA.\n\n'
            f'Клієнт написав у приват:\n'
            f'"""\n{question_text[: self._RAG_QUESTION_PROMPT_MAX_LEN]}\n"""\n\n'
            f'{contact_hint}\n\n'
            f'{live_events_block}'
            f'База FAQ з canonical відповідями:\n\n'
            f'{faq_block}\n\n'
            f'Завдання:\n'
            f'1. Знайди FAQ-match (навіть перефразованого). Якщо жоден не підходить — NO_MATCH.\n'
            f'2. Якщо match — перепиши canonical answer персоналізовано для клієнта:\n'
            f'   - Звертайся ТІЛЬКИ на «Ви» (ніколи «ти» — батьки, не ровесники), 3-6 речень\n'
            f'   - ЗБЕРЕЖИ ключові ЦИФРИ, НАЗВИ ТАБОРІВ, URL з canonical (НЕ вигадуй власні!)\n'
            f'   - Якщо питання про конкретний табір/зміну і він є у LIVE ТАБОРИ — '
            f'додай актуальну доступність: ❗ <30% = FOMO, 🔴 = запропонуй аналог.\n'
            f"   - Якщо є ім'я клієнта — вплети у першу фразу\n"
            f'   - Закінчуй CTA-запитанням (ведемо у діалог, не закриваємо)\n'
            f'   - Емодзі 1-2 максимум\n'
            f'3. Оціни confidence 0.0-1.0 наскільки певен що це саме цей FAQ.\n\n'
            f'КАТЕГОРИЧНО ЗАБОРОНЕНО:\n'
            f'❌ Звертання на «ти/тобі/твій» — завжди «Ви», «Вам», «Ваш», «Ваша дитина»\n'
            f'❌ Просити у чаті ПІБ/дату народження/медичні дані дитини — батьки '
            f'заповнюють картку САМІ у особистому кабінеті і ПІДПИСУЮТЬ. Без підпису '
            f'картка юридичної сили не має, тому ми не маємо права записувати за них.\n'
            f'❌ Слово «доставка» стосовно дітей — ми НЕ вантаж. Правильно: «трансфер», «привезти», «забрати», «супровід»\n'
            f'❌ Вигадувати факти яких нема у canonical (ціни, дати, програми)\n'
            f'❌ Починати з «Дякую за питання» / «Чудове питання» / «Радий вашому коментарю»\n'
            f'❌ «Там все є» / «Все на сайті» — завжди 2-3 конкретних факти, ПОТІМ URL\n'
            f'❌ «11 років — перехідний вік» (для 11 є TDK від 6 до 11)\n'
            f'❌ Агресивно порівнювати з конкурентами\n'
            f'❌ 3 URL підряд без пояснення\n\n'
            f'Формат — STRICT JSON:\n'
            f'{{"faq_id": 42 або null, "confidence": 0.9, "answer": "text"}}\n'
            f'NO_MATCH: {{"faq_id": null, "confidence": 0.0, "answer": ""}}\n'
            f'Поверни ТІЛЬКИ JSON, без пояснень.'
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
                    'max_tokens': 500,
                    'messages': [{'role': 'user', 'content': prompt}],
                },
                timeout=self._ANTHROPIC_API_TIMEOUT,
            )
            if resp.status_code != 200:
                _logger.warning(
                    'SendPulse Odoo: RAG HTTP %d — %s',
                    resp.status_code,
                    resp.text[: self._LOG_TEXT_PREVIEW_LEN],
                )
                return {**empty, 'reason': f'http_{resp.status_code}'}

            raw = (resp.json().get('content') or [{}])[0].get('text', '').strip()
            # Claude іноді обрамляє у ```json ... ```; зрізаємо
            import json as _json
            import re as _re

            m = _re.search(r'\{[\s\S]*?\}', raw)
            if not m:
                _logger.warning(
                    'SendPulse Odoo: RAG no JSON in response — %s',
                    raw[: self._LOG_TEXT_PREVIEW_LEN],
                )
                return {**empty, 'reason': 'no_json'}
            data = _json.loads(m.group(0))
            faq_id_raw = data.get('faq_id')
            confidence = float(data.get('confidence') or 0.0)
            answer = (data.get('answer') or '').strip()

            if not faq_id_raw or not answer:
                return {
                    'matched': False,
                    'faq_id': None,
                    'confidence': confidence,
                    'answer': '',
                    'reason': 'no_match',
                }

            # Normalize faq_id: Claude іноді повертає "FAQ_6" або "6" замість integer
            faq_id = None
            if isinstance(faq_id_raw, int):
                faq_id = faq_id_raw
            elif isinstance(faq_id_raw, str):
                digits = _re.search(r'\d+', faq_id_raw)
                if digits:
                    try:
                        faq_id = int(digits.group(0))
                    except (ValueError, TypeError):
                        pass
            if not faq_id:
                return {
                    'matched': False,
                    'faq_id': None,
                    'confidence': confidence,
                    'answer': '',
                    'reason': 'bad_faq_id',
                }

            # Increment hit count + last_used_at
            faq = Faq.browse(faq_id).exists()
            if faq:
                faq.sudo().write(
                    {
                        'hit_count': faq.hit_count + 1,
                        'last_used_at': fields.Datetime.now(),
                    }
                )

            return {
                'matched': True,
                'faq_id': faq_id,
                'confidence': confidence,
                'answer': answer,
                'reason': 'ok',
            }
        except Exception as e:
            _logger.error('SendPulse Odoo: RAG exception — %s', e)
            return {**empty, 'reason': f'exception: {str(e)[: self._EXCEPTION_MSG_PREVIEW_LEN]}'}

    def _try_rag_auto_answer(self, question_text):
        """
        Helper: якщо RAG дав match з достатнім confidence — надсилає автовідповідь
        клієнту через SendPulse + постить у Discuss-канал з 🤖 маркером.

        Гейт: respects `rag_auto_confidence_threshold` (default 0.85).
        Ідемпотентний — rag_auto_answered_at не дозволяє спамити автовідповіді частіше ніж раз/годину.
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.rag_auto_answer_enabled', 'False') != 'True':
            return

        # V2 F1 guard: RAG НЕ втручається у активну розмову з оператором.
        # Критерії «оператор вже у чаті»:
        #   1. Оператор уже відповідав (sp_first_reply_at не порожнє) — класичний pickup
        #   2. Stage = in_progress — оператор взяв чат у роботу через action_open_discuss
        #   3. У каналі є non-bot members (оператори долучені)
        # Також не лізти у identifying / close.
        if self.stage in ('in_progress', 'close', 'identifying'):
            _logger.info(
                'SendPulse Odoo: RAG skip for connect %s — stage=%s (operator engaged)',
                self.id,
                self.stage,
            )
            return
        if self.sp_first_reply_at:
            _logger.info(
                'SendPulse Odoo: RAG skip for connect %s — operator already replied at %s',
                self.id,
                self.sp_first_reply_at,
            )
            return

        try:
            threshold = float(
                ICP.get_param('odoo_chatwoot_connector.rag_auto_confidence_threshold', '0.85')
            )
        except (ValueError, TypeError):
            threshold = 0.85

        # Rate-limit: якщо нещодавно (< 1h) вже відповіли автоматично — skip
        now = fields.Datetime.now()
        if self.rag_auto_answered_at and (now - self.rag_auto_answered_at) < timedelta(
            hours=self._RAG_AUTO_ANSWER_RATE_LIMIT_HOURS
        ):
            return

        result = self._rag_answer_question(question_text, contact_name=self.name or '')
        if not result.get('matched'):
            return
        if result.get('confidence', 0.0) < threshold:
            _logger.info(
                'SendPulse Odoo: RAG match below threshold for connect %s (conf=%.2f < %.2f)',
                self.id,
                result.get('confidence'),
                threshold,
            )
            return

        answer = result['answer']
        faq_id = result['faq_id']
        try:
            # Шлемо через SendPulse API
            sent = self.send_message_to_sendpulse(answer, attachment_url=None)
            if not sent:
                _logger.warning(
                    'SendPulse Odoo: RAG auto-answer send failed for connect %s', self.id
                )
                return
            # Мітимо розмову
            self.write(
                {
                    'rag_auto_answered_at': now,
                    'rag_last_faq_id': faq_id,
                }
            )
            # Нотатка у Discuss-канал з маркером
            if self.channel_id:
                self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                    body=Markup(
                        '🤖 <b>Auto-answered (RAG FAQ #{faq_id}, confidence {conf:.0%})</b><br/>'
                        '<i>Питання клієнта:</i> {q}<br/>'
                        '<i>Відповідь:</i> {a}'
                    ).format(
                        faq_id=faq_id,
                        conf=result.get('confidence', 0.0),
                        q=escape(question_text[: self._RAG_QUESTION_NOTE_PREVIEW_LEN]),
                        a=escape(answer),
                    ),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            _logger.info(
                'SendPulse Odoo: RAG auto-answered connect %s from FAQ #%s (conf=%.2f)',
                self.id,
                faq_id,
                result.get('confidence', 0.0),
            )
        except Exception as e:
            _logger.error(
                'SendPulse Odoo: RAG auto-answer exception for connect %s: %s', self.id, e
            )
