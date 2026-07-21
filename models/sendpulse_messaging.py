"""
SendPulse ↔ Odoo — Messaging shard.

`_inherit`-шматок `sendpulse.connect` (God Object рефакторинг, крок 14/14,
останній кластер): вихідні повідомлення клієнту через SendPulse API —
per-service ліміти довжини (_SERVICE_TEXT_LIMITS), auto-split довгого тексту
(_split_text_by_limit), відправка одного/кількох chunks
(send_message_to_sendpulse, _send_single_message) — і щогодинний крон
дозавантаження контактів, яких нема в Odoo, з SendPulse API
(_CONTACT_LIST_ENDPOINTS, cron_pull_missing_contacts).
Мовна логіка не змінена — чистий перенос коду з sendpulse_connect.py.
"""

import logging
import time

import requests
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SendpulseConnectMessaging(models.Model):
    _inherit = 'sendpulse.connect'

    # ── Magic-number константи (аудит 19.07.2026, issue #8) ───────────────
    _SENDPULSE_API_TIMEOUT = 15  # requests timeout(s) для send/pull-контактів
    _LOG_RESPONSE_BODY_PREVIEW_LEN = 500  # обрізка resp.text у _logger.info/warning
    _ERROR_RAW_TEXT_PREVIEW_LEN = 200  # обрізка raw resp.text у 400-hint

    # Ліміти SendPulse API по довжині тексту (chars). Перевищення → 400 (#100).
    _SERVICE_TEXT_LIMITS = {
        'telegram': 4096,
        'instagram': 1000,  # SendPulse-side ліміт для IG
        'facebook': 2000,
        'messenger': 2000,
        'whatsapp': 1600,
        'viber': 7000,
        'livechat': 4000,
        'tiktok': 1000,
    }

    @staticmethod
    def _split_text_by_limit(text, max_chars):
        """
        Розбиває текст на частини не довші за max_chars зі збереженням абзаців
        і речень. Стратегія: абзаци → речення → слова → hard cut.
        Повертає list of chunks.
        """
        if not text or len(text) <= max_chars:
            return [text] if text else []

        # Safety margin — залишаємо 20 chars на нумерацію "(1/3) "
        effective_max = max_chars - 20

        def flush(acc, chunks):
            if acc.strip():
                chunks.append(acc.strip())

        chunks = []
        current = ''

        # Крок 1: по абзацах (\n\n)
        paragraphs = text.split('\n\n')
        for para in paragraphs:
            if not para.strip():
                continue
            candidate = (current + '\n\n' + para) if current else para
            if len(candidate) <= effective_max:
                current = candidate
                continue
            # Pending current → flush
            flush(current, chunks)
            current = ''
            # Абзац вміщується сам — стаємо ним
            if len(para) <= effective_max:
                current = para
                continue
            # Абзац занадто довгий — по реченнях
            import re as _re

            sentences = _re.split(r'(?<=[.!?…])\s+', para)
            buf = ''
            for sent in sentences:
                cand2 = (buf + ' ' + sent) if buf else sent
                if len(cand2) <= effective_max:
                    buf = cand2
                    continue
                flush(buf, chunks)
                buf = ''
                if len(sent) <= effective_max:
                    buf = sent
                    continue
                # Речення ще довше — по словах
                words = sent.split(' ')
                wbuf = ''
                for w in words:
                    cand3 = (wbuf + ' ' + w) if wbuf else w
                    if len(cand3) <= effective_max:
                        wbuf = cand3
                    else:
                        flush(wbuf, chunks)
                        # Hard cut якщо навіть одне слово > max
                        while len(w) > effective_max:
                            chunks.append(w[:effective_max])
                            w = w[effective_max:]
                        wbuf = w
                if wbuf:
                    buf = wbuf
            if buf:
                current = buf

        flush(current, chunks)
        return chunks

    def send_message_to_sendpulse(self, text, attachment_url=None):
        """
        Відправляє текстове повідомлення клієнту через SendPulse API.
        Викликається з mail_channel.py при відповіді оператора в Discuss.
        Auto-split: якщо text довший за per-service limit — розбиває на частини
        і шле по черзі. Повертає True якщо ВСІ частини пройшли.
        """
        self.ensure_one()
        if not self.sendpulse_contact_id:
            _logger.warning('SendPulse Odoo: немає contact_id для відправки')
            return False

        # ── V2 F13: Pre-flight check довжини + auto-split ────────────────
        service = self.service or 'telegram'
        limit = self._SERVICE_TEXT_LIMITS.get(service, 2000)
        if text and len(text) > limit:
            chunks = self._split_text_by_limit(text, limit)
            total = len(chunks)
            _logger.info(
                'SendPulse Odoo: text %d chars > %d limit for %s → split into %d chunks',
                len(text),
                limit,
                service,
                total,
            )
            all_ok = True
            for i, chunk in enumerate(chunks, 1):
                prefix = f'({i}/{total}) ' if total > 1 else ''
                piece = prefix + chunk
                # Перша частина несе attachment, решта — лише текст
                att = attachment_url if i == 1 else None
                ok = self._send_single_message(piece, att)
                if not ok:
                    all_ok = False
                    _logger.warning(
                        'SendPulse Odoo: chunk %d/%d failed for contact %s',
                        i,
                        total,
                        self.sendpulse_contact_id,
                    )
                    break
                if i < total:
                    time.sleep(0.7)  # ratelimit-safe pause
            if self.channel_id and total > 1:
                self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                    body=(
                        f'ℹ️ Повідомлення було довше за ліміт {service.title()} ({limit} chars) — '
                        f'автоматично розбите на {total} частин{"" if all_ok else ", АЛЕ не всі пройшли"}.'
                    ),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            return all_ok

        return self._send_single_message(text, attachment_url)

    def _send_single_message(self, text, attachment_url=None):
        """Low-level send — без перевірки довжини (для chunk-sending)."""
        self.ensure_one()
        if not self.sendpulse_contact_id:
            return False

        token = self._get_access_token()
        if not token:
            return False

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }

        # Маршрутизація по сервісу
        service = self.service or 'telegram'
        endpoint_map = {
            'telegram': 'https://api.sendpulse.com/telegram/contacts/send',
            'instagram': 'https://api.sendpulse.com/instagram/contacts/send',
            'facebook': 'https://api.sendpulse.com/facebook/contacts/send',
            'messenger': 'https://api.sendpulse.com/messenger/contacts/send',
            'viber': 'https://api.sendpulse.com/viber/contacts/send',
            'whatsapp': 'https://api.sendpulse.com/whatsapp/contacts/send',
            'livechat': 'https://api.sendpulse.com/livechat/contacts/send',
        }
        endpoint = endpoint_map.get(service, endpoint_map['telegram'])

        # Кожен канал має свій формат payload
        if service == 'telegram':
            payload = {
                'contact_id': self.sendpulse_contact_id,
                'message': {'type': 'text', 'text': text},
            }
            if attachment_url:
                payload['message'] = {'type': 'photo', 'photo': attachment_url}
        elif service == 'messenger':
            # Facebook Messenger: singular message, messaging_type RESPONSE/UPDATE/MESSAGE_TAG
            payload = {
                'contact_id': self.sendpulse_contact_id,
                'message': {'type': 'RESPONSE', 'content_type': 'message', 'text': text},
            }
            if attachment_url:
                payload['message'] = {
                    'type': 'RESPONSE',
                    'content_type': 'message',
                    'text': attachment_url,
                }
        elif service == 'whatsapp':
            # WhatsApp Business API: singular message, text вкладений як {body: "..."}
            payload = {
                'contact_id': self.sendpulse_contact_id,
                'message': {'type': 'text', 'text': {'body': text}},
            }
            if attachment_url:
                payload['message'] = {'type': 'image', 'image': {'link': attachment_url}}
        else:
            messages = []
            if text:
                messages.append({'type': 'text', 'message': {'text': text}})
            if attachment_url:
                messages.append({'type': 'image', 'message': {'url': attachment_url}})
            payload = {
                'contact_id': self.sendpulse_contact_id,
                'messages': messages,
            }

        try:
            _logger.info(
                'SendPulse Odoo: відправляємо в %s contact=%s payload=%s',
                endpoint,
                self.sendpulse_contact_id,
                payload,
            )
            resp = requests.post(
                endpoint, headers=headers, json=payload, timeout=self._SENDPULSE_API_TIMEOUT
            )
            _logger.info(
                'SendPulse Odoo: відповідь API status=%s body=%s',
                resp.status_code,
                resp.text.replace('\n', ' ').replace('\r', '')[
                    : self._LOG_RESPONSE_BODY_PREVIEW_LEN
                ],
            )

            if resp.status_code == 401:
                self._sendpulse_oauth_invalidate_cache()
                token = self._get_access_token(force_refresh=True)
                if token:
                    headers['Authorization'] = f'Bearer {token}'
                    resp = requests.post(
                        endpoint,
                        headers=headers,
                        json=payload,
                        timeout=self._SENDPULSE_API_TIMEOUT,
                    )
                    _logger.info(
                        'SendPulse Odoo: повтор після 401 status=%s body=%s',
                        resp.status_code,
                        resp.text.replace('\n', ' ').replace('\r', '')[
                            : self._LOG_RESPONSE_BODY_PREVIEW_LEN
                        ],
                    )

            # Карта назв каналів для повідомлень оператору
            _SERVICE_LABELS = {
                'telegram': 'Telegram',
                'instagram': 'Instagram',
                'facebook': 'Facebook',
                'messenger': 'Messenger',
                'viber': 'Viber',
                'whatsapp': 'WhatsApp',
                'livechat': 'LiveChat',
                'tiktok': 'TikTok',
            }

            # 400 = контакт неактивний або невалідний запит
            if resp.status_code == 400:
                service_label = _SERVICE_LABELS.get(service, service or 'канал')
                try:
                    err_data = resp.json()
                    contact_errors = (err_data.get('errors') or {}).get('contact_id', [])
                    err_code = contact_errors[0] if contact_errors else ''
                except Exception:
                    err_code = ''

                if err_code == 'contact.errors.not_active':
                    if service in ('messenger', 'facebook'):
                        hint = (
                            'Facebook Messenger: вікно 24 години закрите — '
                            'клієнт не писав першим більше доби. '
                            'Надсилати через Messenger вже немає сенсу. '
                            'Зверніться через інший канал (WhatsApp, email).'
                        )
                    else:
                        hint = (
                            f'Контакт неактивний у {service_label} — '
                            'клієнт відписався від бота або заблокував його.'
                        )
                else:
                    raw = (
                        (resp.text or '')
                        .replace('\n', ' ')
                        .strip()[: self._ERROR_RAW_TEXT_PREVIEW_LEN]
                    )
                    hint = f'API відхилив запит. Код: {err_code or raw or "невідомо"}.'

                _logger.warning(
                    'SendPulse Odoo: 400 for %s contact=%s (%s): %s',
                    service,
                    self.sendpulse_contact_id,
                    self.name,
                    err_code,
                )
                if self.channel_id:
                    self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                        body=f'❌ Повідомлення не доставлено у {service_label}.\n{hint}',
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                        author_id=self.env.ref('base.partner_root').id,
                    )
                return False

            # 422 = provider policy/payload rejection (not always the same reason).
            if resp.status_code == 422:
                service_label = _SERVICE_LABELS.get(service, service or 'канал')
                raw_reason = (resp.text or '').replace('\n', ' ').replace('\r', ' ').strip()
                short_reason = raw_reason[:220] if raw_reason else 'Без деталей від API.'
                _logger.warning(
                    'SendPulse Odoo: 422 for %s contact=%s (%s): %s',
                    service,
                    self.sendpulse_contact_id,
                    self.name,
                    short_reason,
                )
                # Розбираємо тіло відповіді щоб дати точну підказку
                try:
                    err_data = resp.json()
                    err_code = err_data.get('error_code')
                    err_errors = err_data.get('errors', {})
                    err_text = ' '.join(
                        str(v)
                        for vals in err_errors.values()
                        for v in (vals if isinstance(vals, list) else [vals])
                    ).lower()
                except Exception:
                    err_code = None
                    err_text = ''

                if err_code == 403 or 'blocked by the user' in err_text or 'forbidden' in err_text:
                    policy_hint = (
                        f'Клієнт заблокував бота у {service_label}. '
                        "Написати через цей канал більше неможливо — зверніться через інший спосіб зв'язку."
                    )
                elif 'invalid' in err_text or 'invalid data' in err_text:
                    policy_hint = (
                        f'API {service_label} відхилив повідомлення: невалідний формат. '
                        'Можливо тип вкладення не підтримується (Instagram не підтримує PDF/документи).'
                    )
                elif service in ('messenger', 'facebook', 'instagram'):
                    policy_hint = (
                        f'Вікно відповіді {service_label} закрите (24 години). '
                        'Зверніться через інший канал (WhatsApp, email).'
                    )
                else:
                    policy_hint = (
                        'Можлива причина: вікно відповіді для каналу закрите '
                        'або формат повідомлення не прийнято API.'
                    )
                if self.channel_id:
                    self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                        body=(
                            f'⚠️ Повідомлення не доставлено у {service_label}.\n'
                            f'{policy_hint}\nAPI: {short_reason}'
                        ),
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                        author_id=self.env.ref('base.partner_root').id,
                    )
                return False

            resp.raise_for_status()
            _logger.info(
                'SendPulse Odoo: повідомлення відправлено контакту %s', self.sendpulse_contact_id
            )
            # Метрики: фіксуємо першу відповідь оператора
            if not self.sp_first_reply_at:
                update_metrics = {'sp_first_reply_at': fields.Datetime.now()}
                if self.sp_funnel_stage in (
                    'comment_only',
                    'private_sent',
                    'customer_replied',
                    False,
                    None,
                ):
                    update_metrics['sp_funnel_stage'] = 'operator_engaged'
                self.sudo().write(update_metrics)
            return True
        except Exception as e:
            _logger.error('SendPulse Odoo: помилка відправки: %s', e)
            if self.channel_id:
                self.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                    body=f'❌ Помилка відправки повідомлення: {e}',
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            return False

    # ════════════════════════════════════════════════════════════════════
    # Cron: Pull Missing Contacts from SendPulse API
    # ════════════════════════════════════════════════════════════════════

    _CONTACT_LIST_ENDPOINTS = {
        'telegram': 'https://api.sendpulse.com/telegram/contacts',
        'instagram': 'https://api.sendpulse.com/instagram/contacts',
        'facebook': 'https://api.sendpulse.com/facebook/contacts',
        'viber': 'https://api.sendpulse.com/viber/contacts',
        'whatsapp': 'https://api.sendpulse.com/whatsapp/contacts',
    }

    @api.model
    def cron_pull_missing_contacts(self):
        """
        Щогодинний крон: тягне активні контакти з SendPulse API та
        створює в Odoo ті що відсутні. Якщо всі є — нічого не робить.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        client_id = ICP.get_param('odoo_chatwoot_connector.client_id', '')
        client_secret = ICP.get_param('odoo_chatwoot_connector.client_secret', '')
        if not client_id or not client_secret:
            _logger.warning('SendPulse cron_pull: client_id/secret не налаштовані')
            return

        # Отримуємо токен через singleton-запис (будь-який активний)
        sample = self.search([], limit=1)
        if not sample:
            _logger.info('SendPulse cron_pull: нема жодного connect-запису, пропускаємо')
            return
        token = sample._get_access_token()
        if not token:
            _logger.warning('SendPulse cron_pull: не вдалося отримати токен')
            return

        # Збираємо унікальні (service, bot_id) з існуючих записів
        self.env.cr.execute("""
            SELECT DISTINCT service, bot_id
            FROM sendpulse_connect
            WHERE service IS NOT NULL AND bot_id IS NOT NULL
        """)
        bots = self.env.cr.fetchall()
        if not bots:
            _logger.info('SendPulse cron_pull: нема ботів для перевірки')
            return

        total_created = 0
        total_updated = 0

        for service, bot_id in bots:
            endpoint = self._CONTACT_LIST_ENDPOINTS.get(service)
            if not endpoint:
                continue

            # Тягнемо контакти з SendPulse по 100 за раз
            offset = 0
            page_size = 100
            while True:
                try:
                    resp = requests.get(
                        endpoint,
                        params={'bot_id': bot_id, 'from': offset, 'count': page_size},
                        headers={'Authorization': f'Bearer {token}'},
                        timeout=self._SENDPULSE_API_TIMEOUT,
                    )
                    if resp.status_code == 401:
                        self._sendpulse_oauth_invalidate_cache()
                        token = sample._get_access_token(force_refresh=True)
                        if not token:
                            _logger.warning('SendPulse cron_pull: 401 і не вдалося оновити токен')
                            break
                        resp = requests.get(
                            endpoint,
                            params={'bot_id': bot_id, 'from': offset, 'count': page_size},
                            headers={'Authorization': f'Bearer {token}'},
                            timeout=self._SENDPULSE_API_TIMEOUT,
                        )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    _logger.warning(
                        'SendPulse cron_pull: помилка API %s bot=%s: %s', service, bot_id, e
                    )
                    break

                contacts = data if isinstance(data, list) else data.get('data', [])
                if not contacts:
                    break

                # ID контактів що вже є в Odoo
                sp_ids = [c.get('id') for c in contacts if c.get('id')]
                existing = self.search([('sendpulse_contact_id', 'in', sp_ids)])
                existing_ids = set(existing.mapped('sendpulse_contact_id'))

                for contact in contacts:
                    cid = contact.get('id')
                    if not cid:
                        continue

                    if cid not in existing_ids:
                        # Контакту нема — створюємо
                        name = contact.get('name') or contact.get('username') or 'Невідомий'
                        new_rec = self.create(
                            {
                                'sendpulse_contact_id': cid,
                                'name': name,
                                'service': service,
                                'bot_id': bot_id,
                            }
                        )
                        # Підтягуємо повний профіль з API
                        try:
                            new_rec.action_fetch_contact_info()
                        except Exception as e:
                            _logger.warning('SendPulse cron_pull: fetch_info failed %s: %s', cid, e)
                        total_created += 1
                        _logger.info('SendPulse cron_pull: створено контакт %s (%s)', name, cid)
                    else:
                        # Контакт є — перевіряємо чи потрібне оновлення
                        rec = existing.filtered(lambda r: r.sendpulse_contact_id == cid)
                        if rec and not rec.avatar_url:
                            try:
                                rec.action_fetch_contact_info()
                                total_updated += 1
                            except Exception as e:
                                _logger.warning('SendPulse cron_pull: update failed %s: %s', cid, e)

                if len(contacts) < page_size:
                    break
                offset += page_size

        if total_created or total_updated:
            _logger.info(
                'SendPulse cron_pull: завершено — створено: %d, оновлено: %d',
                total_created,
                total_updated,
            )
        else:
            _logger.debug('SendPulse cron_pull: всі контакти в Odoo, нічого не змінено')
