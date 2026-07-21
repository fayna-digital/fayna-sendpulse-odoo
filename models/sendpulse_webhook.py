"""
SendPulse ↔ Odoo — Webhook processing shard.

`_inherit`-шматок `sendpulse.connect` (God Object рефакторинг, крок 13/14):
обробка вхідних/вихідних SendPulse webhook-подій — `_process_incoming_event`
(основний inbound flow: ідентифікація партнера, race-guard advisory lock,
create/update розмови, збереження повідомлення, медіа-вкладення),
`_process_outgoing_event` (backfill пропущеного incoming з outbound-події),
`_process_unsubscribe` (закриття розмови при відписці) і медіа-хелпери
завантаження вкладень (`_is_allowed_media_url` SSRF guard,
`_download_media_as_attachment`).
Мовна логіка не змінена — чистий перенос коду з sendpulse_connect.py.
"""

import base64
import hashlib
import logging
from datetime import timedelta

import requests
from markupsafe import Markup, escape
from odoo import api, fields, models

from .sendpulse_connect import _SENDPULSE_INBOUND_LOCK_KEY2

_logger = logging.getLogger(__name__)


class SendpulseConnectWebhook(models.Model):
    _inherit = 'sendpulse.connect'

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
        # ── Перевірка: чи це коментар під постом FB/IG ─────────────────────
        channel_data_msg = (
            ((data.get('info') or {}).get('message') or {}).get('channel_data') or {}
        ).get('message') or {}
        is_comment = isinstance(channel_data_msg, dict) and (
            # Facebook format: item/verb
            (channel_data_msg.get('item') == 'comment' and channel_data_msg.get('verb') == 'add')
            # Instagram via SendPulse: media.media_product_type == FEED
            or (
                isinstance(channel_data_msg.get('media'), dict)
                and channel_data_msg['media'].get('media_product_type') == 'FEED'
            )
        )
        if is_comment:
            return self._process_comment_event(
                data=data,
                contact=contact,
                bot=bot,
                service=service,
                channel_data_msg=channel_data_msg,
            )

        contact_id = contact.get('id', '')
        contact_name = contact.get('name', 'Невідомий')
        email = contact.get('email', '') or ''
        phone = contact.get('phone', '') or ''
        last_message = contact.get('last_message', '') or ''
        variables = contact.get('variables', {}) or {}

        # Визначаємо тип медіа з last_message_data (якщо є)
        last_message_data = contact.get('last_message_data', {}) or {}
        msg_data = last_message_data.get('message', {}) or {}
        msg_type = (
            msg_data.get('type', 'text') or 'text'
        )  # text, image, sticker, audio, video, document

        # Fallback: якщо last_message виглядає як media URL — вважаємо image
        _MEDIA_URL_PATTERNS = ('lookaside.fbsbx.com', '/messages/media', 'chatbots-service')
        _MEDIA_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mp3', '.ogg')
        if msg_type == 'text' and last_message.startswith('http'):
            if any(p in last_message for p in _MEDIA_URL_PATTERNS) or any(
                last_message.lower().endswith(e) for e in _MEDIA_EXTENSIONS
            ):
                msg_type = 'image'

        # Соціальні ідентифікатори
        social_username = (
            variables.get('username')
            or variables.get('telegram_username')
            or contact.get('username', '')
        )
        social_profile_url = (
            variables.get('profile_url')
            or variables.get('facebook_url')
            or variables.get('instagram_url')
            or ''
        )
        # Для Telegram будуємо URL профілю з username якщо немає
        if not social_profile_url and social_username and service == 'telegram':
            social_profile_url = f'https://t.me/{social_username}'

        # Фото контакту з webhook
        photo_url = (contact.get('photo') or contact.get('profile_pic') or '').strip() or ''

        # ── Bot-змінні ────────────────────────────────────────────────────
        sp_child_name = (variables.get('child_name') or '').strip() or False
        sp_booking_email = (variables.get('booking_email') or '').strip() or False
        # Якщо email порожній у контакті — беремо з user_email бота
        effective_email = email or (variables.get('user_email') or '').strip()

        # ── Крок 1: Ідентифікація партнера ──────────────────────────────
        partner = self._find_partner(contact_id, effective_email, phone, variables=variables)

        # ── Race-guard: advisory lock на (contact_id, service) ──────────
        # Два одночасних webhook-и (new_subscriber + incoming_message за ~1 сек)
        # раніше створювали два записи (search→∅→create у обох). Тепер другий
        # чекає COMMIT першого, тоді бачить створений запис і оновлює його
        # замість створення дублю. Авто-привітання теж не дублюється бо
        # is_brand_new=False у другого.
        if contact_id:
            lock_key1 = (
                int(hashlib.md5(f'{contact_id}|{service}'.encode()).hexdigest()[:8], 16)
                & 0x7FFFFFFF
            )
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(%s, %s)',
                (lock_key1, _SENDPULSE_INBOUND_LOCK_KEY2),
            )
            # Примусовий flush + invalidate cache щоб search після lock
            # повертав актуальний стан (включно з записом створеним іншим
            # worker-ом який щойно commit-нув).
            self.env.flush_all()
            self.env.invalidate_all()

        # ── Крок 2: Знаходимо або створюємо розмову ─────────────────────
        # Пріоритет 1: активна розмова по sendpulse_contact_id + service
        connect = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
            ],
            limit=1,
        )

        # Пріоритет 2: якщо партнер відомий — шукаємо активний чат по partner_id + service.
        # Це запобігає створенню дублікатів коли один реальний клієнт має кілька
        # контактів у SendPulse (наприклад, тестовий + реальний).
        if not connect and partner:
            connect = self.search(
                [
                    ('partner_id', '=', partner.id),
                    ('service', '=', service),
                    ('stage', '!=', 'close'),
                ],
                order='write_date desc',
                limit=1,
            )
            if connect and connect.sendpulse_contact_id != contact_id:
                # Оновлюємо contact_id на актуальний
                connect.write({'sendpulse_contact_id': contact_id})

        # Пріоритет 3: закрита розмова того ж контакту — перевідкриваємо замість створення нової
        if not connect:
            connect = self.search(
                [
                    ('sendpulse_contact_id', '=', contact_id),
                    ('service', '=', service),
                    ('stage', '=', 'close'),
                ],
                order='write_date desc',
                limit=1,
            )
            if connect:
                connect.write({'stage': 'new'})
                # Розархівовуємо discuss.channel якщо він був архівований при закритті
                if connect.channel_id:
                    connect.channel_id.write({'active': True})

        now = fields.Datetime.now()
        is_brand_new = not connect  # True тільки якщо connect щойно буде створено
        if not connect:
            create_vals = {
                'name': contact_name,
                'sendpulse_contact_id': contact_id,
                'service': service,
                'bot_id': bot.get('id', ''),
                'bot_name': bot.get('name', ''),
                'sp_child_name': sp_child_name or False,
                'sp_booking_email': sp_booking_email or False,
                'partner_id': partner.id if partner else False,
                'unidentified_email': effective_email if not partner else False,
                'unidentified_phone': phone if not partner else False,
                'social_username': social_username or False,
                'social_profile_url': social_profile_url or False,
                'last_message_preview': last_message[:100] if last_message else '',
                'last_message_date': now,
                'stage': 'new',
            }
            # Partial unique index у init() фізично блокує дублі. Ловимо
            # IntegrityError через savepoint, якщо випадково створюємо дубль —
            # відкочуємо create і підхоплюємо existing запис.
            from psycopg2 import IntegrityError

            try:
                with self.env.cr.savepoint():
                    connect = self.create(create_vals)
            except IntegrityError:
                _logger.info(
                    'SendPulse Odoo: race duplicate intercepted by unique index — '
                    'contact=%s service=%s',
                    contact_id,
                    service,
                )
                self.env.invalidate_all()
                connect = self.search(
                    [
                        ('sendpulse_contact_id', '=', contact_id),
                        ('service', '=', service),
                        ('stage', '!=', 'close'),
                    ],
                    limit=1,
                )
                if not connect:
                    # Дуже дивний стан — IntegrityError на unique, але search не знаходить
                    raise
                is_brand_new = False
            else:
                # Fallback race-guard (backup до unique index): find older duplicate
                duplicate = self.search(
                    [
                        ('sendpulse_contact_id', '=', contact_id),
                        ('service', '=', service),
                        ('stage', '!=', 'close'),
                        ('id', '<', connect.id),
                    ],
                    limit=1,
                )
                if duplicate:
                    connect.unlink()
                    connect = duplicate
                    is_brand_new = False

            # V2 F3: якщо brand-new і без партнера — бот сам запитає email
            # замість stage=new (чекання оператора). Повертає True якщо flow запустився.
            if is_brand_new and not partner:
                if connect._try_start_identification():
                    # Bot-wizard активний — не продовжуємо normal flow
                    # (не шлемо auto-greeting, не постимо у канал як стандартний inbound)
                    return connect
        else:
            # V2 F3: якщо розмова на стадії identifying — спробуємо parse email з inbound
            if connect.stage == 'identifying':
                handled = connect._try_advance_identification(last_message or '')
                if handled and connect.stage == 'identifying':
                    # Все ще identifying (retry) — не продовжуємо normal flow
                    return connect
                # Якщо identifying завершилось (done/gave_up) — продовжуємо з update_vals
                # щоб повідомлення клієнта потрапило у chatter як нормально

            # Оновлюємо існуючу розмову
            update_vals = {
                'last_message_preview': last_message[:100]
                if last_message
                else connect.last_message_preview,
                'last_message_date': now,
                'stage': 'new_message' if connect.stage == 'in_progress' else connect.stage,
                # Клієнт написав → вікно 24h відновлюється
                'sp_messenger_window_expires_at': now + timedelta(hours=24),
                'sp_window_alert_sent': False,
            }
            # Метрики: перший inbound від клієнта
            if not connect.sp_first_inbound_at:
                update_vals['sp_first_inbound_at'] = now
            # Funnel: comment_only/private_sent → customer_replied
            if connect.sp_funnel_stage in ('comment_only', 'private_sent', False, None):
                update_vals['sp_funnel_stage'] = 'customer_replied'
            if not connect.partner_id and partner:
                update_vals['partner_id'] = partner.id
            if social_username and not connect.social_username:
                update_vals['social_username'] = social_username
            if social_profile_url and not connect.social_profile_url:
                update_vals['social_profile_url'] = social_profile_url
            # Оновлюємо bot-змінні якщо вони з'явились (бот міг зібрати їх пізніше)
            if sp_child_name and not connect.sp_child_name:
                update_vals['sp_child_name'] = sp_child_name
            if sp_booking_email and not connect.sp_booking_email:
                update_vals['sp_booking_email'] = sp_booking_email
            connect.write(update_vals)

            # V2 F4: Auto-create crm.lead коли клієнт вперше відповідає у приват
            # (comment_only / private_sent → customer_replied). Ідемпотентно:
            # вже є sp_lead_id → skip. No-op якщо auto_create_lead_enabled=False.
            if update_vals.get('sp_funnel_stage') == 'customer_replied':
                connect._auto_create_crm_lead()
                # F9 A/B: зарахувати конверсію шаблону публічної відповіді (ідемпотентно)
                if (
                    connect.sp_public_template_id
                    and not connect.sp_public_template_conversion_counted
                ):
                    connect.sp_public_template_id.bump_customer_replied()
                    connect.write({'sp_public_template_conversion_counted': True})

            # V2 F1: RAG FAQ auto-answer — якщо клієнт написав питання
            # і ми маємо високий confidence на FAQ match → відповідаємо автоматично.
            # Умови: не comment-розмова, клієнт написав текст, не оператор.
            if last_message and not connect.sp_is_comment:
                connect._try_rag_auto_answer(last_message)

        # Ensure incoming Discuss messages always have a customer author,
        # never fallback to OdooBot (it breaks identity/avatar in chat UI).
        author_partner = connect.partner_id
        if not author_partner and partner:
            author_partner = partner
        if not author_partner:
            author_partner = self.env['res.partner'].search(
                [('sendpulse_contact_id', '=', contact_id)],
                order='id desc',
                limit=1,
            )
        if not author_partner:
            create_vals = {
                'name': contact_name or f'{service}:{contact_id}',
                'sendpulse_contact_id': contact_id,
            }
            if effective_email:
                create_vals['email'] = effective_email
            if phone:
                clean_phone = phone.strip().replace(' ', '')
                if clean_phone:
                    create_vals['phone'] = clean_phone
            author_partner = self.env['res.partner'].sudo().create(create_vals)
        if author_partner and not connect.partner_id:
            connect.write({'partner_id': author_partner.id})

        # ── Крок 3: Зберігаємо повідомлення ─────────────────────────────
        if last_message:
            is_image = msg_type in ('image', 'sticker')
            is_media = is_image or msg_type in ('audio', 'video', 'document')
            media_icons = {'audio': '🎵', 'video': '🎥', 'document': '📄'}

            # post_to_channel/record_partner_message=False: тут між create і
            # message_post є _check_and_record_unsubscribe (RODO), а сам
            # message_post має 3 гілки залежно від типу медіа/успіху завантаження
            # вкладення — обидва лишені на місці нижче, без змін.
            new_msg = self._record_conversation_message(
                connect,
                direction='incoming',
                sendpulse_contact_id=contact_id,
                message_type='image' if is_image else ('file' if is_media else 'text'),
                text_message='' if is_media else last_message,
                attachment_url=last_message if is_media else False,
                raw_json={'text': last_message, 'contact': contact},
                date=now,
                post_to_channel=False,
                record_partner_message=False,
            )

            # RODO: детектим unsubscribe-фрази — фіксуємо withdrawal для
            # усіх lead-magnet purposes на цьому connect.
            if not is_media and last_message:
                connect._check_and_record_unsubscribe(last_message, new_msg)

            # Якщо є активний channel — постимо туди для операторів
            if connect.channel_id:
                att = None
                if is_media:
                    att = connect._download_media_as_attachment(last_message)

                if is_image and att:
                    # Фото/стікер — скачали і показуємо як attachment.
                    # Імʼя автора Discuss малює у header bubble з author_id — у body дублювати не треба.
                    connect.channel_id.with_context(sendpulse_incoming=True).message_post(
                        body='',
                        attachment_ids=[att.id],
                        author_id=author_partner.id if author_partner else False,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                elif is_media and att:
                    icon = media_icons.get(msg_type, '📎')
                    base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                    file_url = f'{base_url}/web/content/{att.id}?access_token={att.access_token}'
                    body = Markup("{} <a href='{}' target='_blank'>Вкладення</a>").format(
                        icon, file_url
                    )
                    connect.channel_id.with_context(sendpulse_incoming=True).message_post(
                        body=body,
                        author_id=author_partner.id if author_partner else False,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                else:
                    # Текст або fallback якщо медіа не вдалося завантажити
                    if is_media:
                        icon = media_icons.get(msg_type, '📎')
                        body = Markup("{} <a href='{}' target='_blank'>Вкладення</a>").format(
                            icon, last_message
                        )
                    else:
                        body = escape(last_message)
                    connect.channel_id.with_context(sendpulse_incoming=True).message_post(
                        body=body,
                        author_id=author_partner.id if author_partner else False,
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )

            # Зберігаємо у вкладці Messaging картки партнера
            if connect.partner_id:
                if is_image:
                    partner_body = f"<img src='{last_message}' style='max-width:300px;'/>"
                elif is_media:
                    icon = media_icons.get(msg_type, '📎')
                    partner_body = f"<p>{icon} <a href='{last_message}'>Вкладення</a></p>"
                else:
                    partner_body = f'<p>{last_message}</p>'
                self.env['partner.sendpulse.message'].create(
                    {
                        'partner_id': connect.partner_id.id,
                        'date': now,
                        'text_message': partner_body,
                        'service': service,
                        'direction': 'incoming',
                    }
                )

        # ── Крок 4: Оновлюємо канали партнера ───────────────────────────
        if connect.partner_id:
            connect._update_partner_source()

        # ── Крок 5: Якщо немає каналу — створюємо discuss.channel ──────
        if not connect.channel_id:
            connect._create_discuss_channel(send_greeting=is_brand_new)

        return connect

    @api.model
    def _process_outgoing_event(self, contact, service, timestamp_ms):
        """
        Обробляє outbound_message / outgoing_message events.

        У payload.contact.last_message SendPulse завжди тримає ОСТАННЄ
        КЛІЄНТСЬКЕ повідомлення (не текст оператора). Використовуємо це
        для backfill missed incoming — SendPulse іноді не шле окремий
        incoming_message webhook коли new_subscriber і перший текст
        клієнта приходять з дуже малою різницею у часі.
        """
        contact_id = contact.get('id', '')
        last_message = contact.get('last_message', '') or ''

        if not last_message or not contact_id:
            return

        # Guard: якщо цей текст уже є як incoming → нічого робити не треба
        already_incoming = self.env['sendpulse.message'].search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('direction', '=', 'incoming'),
                ('text_message', '=', last_message),
            ],
            limit=1,
        )
        if already_incoming:
            return

        # Знаходимо активну розмову
        connect = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
            ],
            limit=1,
        )
        if not connect:
            return

        # ── Backfill MISSED incoming ────────────────────────────────────────
        # Текст клієнта якого немає у incoming → SendPulse пропустив webhook.
        # Створюємо як incoming з поміткою у channel.
        now = fields.Datetime.now()
        _logger.info(
            'SendPulse Odoo: backfill missed incoming для contact=%s: %r',
            contact_id,
            last_message[:80],
        )

        author_id = (
            connect.partner_id.id if connect.partner_id else self.env.ref('base.partner_root').id
        )
        # Тут (на відміну від greeting і incoming-media сайтів) create → post →
        # partner-create йдуть підряд без жодного side-effecting виклику між
        # ними в оригінальному коді — тому єдиний виклик helper-а безпечний і
        # відтворює той самий порядок.
        self._record_conversation_message(
            connect,
            direction='incoming',
            sendpulse_contact_id=contact_id,
            message_type='text',
            text_message=last_message,
            raw_json={'text': last_message, 'source': 'backfill_from_outgoing_event'},
            date=now,
            channel_body=Markup(
                '<p><em>(backfill — SendPulse пропустив webhook)</em><br/>{}</p>'
            ).format(escape(last_message)),
            channel_author_id=author_id,
            partner_body=f'<p>👤 {last_message}</p>',
        )

        update_vals = {
            'last_message_preview': last_message[:100],
            'last_message_date': now,
        }
        # Клієнт написав → вікно 24h відновлюється
        update_vals['sp_messenger_window_expires_at'] = now + timedelta(hours=24)
        update_vals['sp_window_alert_sent'] = False
        if connect.sp_funnel_stage in ('comment_only', 'private_sent', False, None):
            update_vals['sp_funnel_stage'] = 'customer_replied'
        if connect.stage == 'in_progress':
            update_vals['stage'] = 'new_message'
        connect.write(update_vals)

    @api.model
    def _process_unsubscribe(self, contact_id, service):
        """Відмічає розмову як закриту при відписці клієнта."""
        connects = self.search(
            [
                ('sendpulse_contact_id', '=', contact_id),
                ('service', '=', service),
                ('stage', '!=', 'close'),
            ]
        )
        for connect in connects:
            connect.write({'stage': 'close'})
            _logger.info(
                'SendPulse Odoo: контакт %s відписався (%s), розмова закрита',
                contact_id,
                service,
            )

    _ALLOWED_MEDIA_DOMAINS = ('sendpulse.com', 'sendpulse.net')
    _MEDIA_MAX_BYTES = 20 * 1024 * 1024  # 20 MB

    @staticmethod
    def _is_allowed_media_url(url):
        """SSRF guard: дозволяємо завантажувати медіа лише з доменів SendPulse."""
        from urllib.parse import urlparse

        try:
            host = (urlparse(url).hostname or '').lower()
            allowed = SendpulseConnectWebhook._ALLOWED_MEDIA_DOMAINS
            return host in allowed or any(host.endswith('.' + d) for d in allowed)
        except Exception:
            return False

    def _download_media_as_attachment(self, media_url):
        """
        Download media file from SendPulse API (requires Bearer token) and
        save as ir.attachment so Odoo can display it inline in Discuss.
        Returns ir.attachment record or None on failure.
        """
        try:
            # SSRF guard
            if not self._is_allowed_media_url(media_url):
                _logger.warning(
                    'SendPulse Odoo: заблоковано URL не з домену SendPulse: %s', media_url
                )
                return None

            token = self._get_access_token()
            if not token:
                return None

            def _fetch(t):
                return requests.get(
                    media_url,
                    headers={'Authorization': f'Bearer {t}'},
                    timeout=30,
                    stream=True,
                )

            resp = _fetch(token)
            if resp.status_code == 401:
                self._sendpulse_oauth_invalidate_cache()
                token = self._get_access_token(force_refresh=True)
                if token:
                    resp = _fetch(token)
            resp.raise_for_status()

            # Перевіряємо оголошений розмір перед завантаженням
            content_length = resp.headers.get('Content-Length')
            if content_length:
                try:
                    if int(content_length) > self._MEDIA_MAX_BYTES:
                        _logger.warning(
                            'SendPulse Odoo: медіа завелике (%s байт), пропускаємо', content_length
                        )
                        return None
                except ValueError:
                    pass

            content_type = resp.headers.get('Content-Type', 'image/jpeg').split(';')[0].strip()
            ext_map = {
                'image/jpeg': 'jpg',
                'image/png': 'png',
                'image/gif': 'gif',
                'image/webp': 'webp',
                'video/mp4': 'mp4',
                'audio/ogg': 'ogg',
                'audio/mpeg': 'mp3',
                'application/pdf': 'pdf',
            }
            ext = ext_map.get(content_type, 'bin')
            filename = f'sendpulse_{fields.Datetime.now().strftime("%Y%m%d_%H%M%S")}.{ext}'

            # Потокове завантаження з жорстким лімітом
            data = b''
            for chunk in resp.iter_content(8192):
                data += chunk
                if len(data) > self._MEDIA_MAX_BYTES:
                    _logger.warning('SendPulse Odoo: медіа перевищило 20 MB ліміт, скасовуємо')
                    return None

            att = self.env['ir.attachment'].create(
                {
                    'name': filename,
                    'datas': base64.b64encode(data).decode(),
                    'mimetype': content_type,
                }
            )
            att.generate_access_token()
            return att
        except Exception as e:
            _logger.warning('SendPulse Odoo: не вдалося завантажити медіа %s: %s', media_url, e)
            return None
