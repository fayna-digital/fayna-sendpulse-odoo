import logging
import time
from datetime import datetime, timedelta

import requests
from markupsafe import Markup
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SendpulseConnectMetaApi(models.Model):
    _inherit = 'sendpulse.connect'

    def _log_fb_audit(self, label, url, payload, status_code, response_text, attempts_used=1):
        """
        Зберігає запис про FB/IG API виклик у ir.logging для аудиту і дебагу.
        Токен з payload редактується (замінюється на '***REDACTED***').
        """
        try:
            redacted = {
                k: ('***REDACTED***' if k == 'access_token' else v)
                for k, v in (payload or {}).items()
            }
            level = 'INFO' if status_code == 200 else 'WARNING'
            short_resp = (response_text or '')[:500]
            msg = (
                f'[{label}] {status_code} attempts={attempts_used}\n'
                f'URL: {url}\n'
                f'Payload: {redacted}\n'
                f'Response: {short_resp}'
            )
            self.env['ir.logging'].sudo().create(
                {
                    'name': 'odoo_chatwoot_connector.fb_api',
                    'type': 'server',
                    'level': level,
                    'dbname': self.env.cr.dbname,
                    'message': msg,
                    'path': 'sendpulse_connect._fb_post_with_retry',
                    'func': label,
                    'line': '0',
                }
            )
        except Exception as e:
            # Аудит-лог не повинен ламати основний флоу
            _logger.warning('SendPulse Odoo: audit log write failed — %s', e)

    def _fb_post_with_retry(self, url, payload, label='fb-call', attempts=3, base_delay=1):
        """
        POST на Graph API з exponential backoff (1s, 3s, 9s).
        Retry на: мережеві помилки, 5xx, 429 (rate limited).
        Не retry на: 4xx (крім 429) — це permanent errors (invalid token, blocked user, etc.).
        Повертає (success: bool, error: str|None, response_json: dict|None).
        """
        last_err = None
        last_status = 0
        last_text = ''
        for attempt in range(attempts):
            try:
                resp = requests.post(url, json=payload, timeout=15)
                last_status = resp.status_code
                last_text = resp.text or ''
                if resp.status_code == 200:
                    self._log_fb_audit(label, url, payload, 200, last_text, attempt + 1)
                    try:
                        return True, None, resp.json()
                    except Exception:
                        return True, None, {}
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    last_err = self._parse_fb_error(resp)
                    _logger.warning(
                        'SendPulse Odoo %s attempt %d/%d → HTTP %d (%s) — retrying',
                        label,
                        attempt + 1,
                        attempts,
                        resp.status_code,
                        last_err,
                    )
                else:
                    err = self._parse_fb_error(resp)
                    _logger.warning('SendPulse Odoo %s failed (no retry) — %s', label, err)
                    self._log_fb_audit(
                        label, url, payload, resp.status_code, last_text, attempt + 1
                    )
                    # V2 immediate alert: якщо токен протух (code 190) — одразу Telegram,
                    # не чекаємо weekly cron. Rate-limited 1/год щоб не спамити.
                    self._maybe_alert_token_expired(err, last_text)
                    return False, err, None
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = str(e)
                last_text = f'network error: {e}'
                _logger.warning(
                    'SendPulse Odoo %s attempt %d/%d → network error (%s) — retrying',
                    label,
                    attempt + 1,
                    attempts,
                    e,
                )
            except Exception as e:
                _logger.error('SendPulse Odoo %s exception — %s', label, e)
                self._log_fb_audit(label, url, payload, 0, f'exception: {e}', attempt + 1)
                return False, str(e), None
            if attempt < attempts - 1:
                time.sleep(base_delay * (3**attempt))
        _logger.error('SendPulse Odoo %s — all %d retries exhausted: %s', label, attempts, last_err)
        self._log_fb_audit(label, url, payload, last_status, last_text, attempts)
        return False, f'retries exhausted: {last_err}', None

    @api.model
    def _maybe_alert_token_expired(self, err_text, raw_response):
        """
        Якщо Graph API відповів помилкою з кодом 190 (token issue) — одразу
        шле loud Telegram-алерт, не чекаючи weekly cron. Rate-limit 1/год
        щоб під DDoS коментарів не спамило сотнями повідомлень.
        """
        combined = f'{err_text or ""} {raw_response or ""}'.lower()
        # Meta error code 190 = invalid/expired token (також часті rbacs 102/104)
        is_token_issue = (
            'код 190' in combined
            or 'code":190' in combined
            or 'code": 190' in combined
            or 'session has expired' in combined
            or 'invalid oauth' in combined
            or 'error validating access token' in combined
        )
        if not is_token_issue:
            return
        ICP = self.env['ir.config_parameter'].sudo()
        last_alert_iso = ICP.get_param('odoo_chatwoot_connector.fb_token_invalid_last_alert_at', '')
        now = fields.Datetime.now()
        if last_alert_iso:
            try:
                last_alert = fields.Datetime.from_string(last_alert_iso)
                if last_alert and (now - last_alert) < timedelta(hours=1):
                    return  # rate-limit
            except Exception:
                pass
        ICP.set_param(
            'odoo_chatwoot_connector.fb_token_invalid_last_alert_at',
            fields.Datetime.to_string(now),
        )
        self._notify_telegram(
            '🚨 <b>FB Page Token НЕДІЙСНИЙ</b>\n\n'
            'API миттєво відхиляє запити — автовідповіді на коменти і '
            'приватні повідомлення НЕ проходять.\n\n'
            '<b>Терміново:</b> отримай новий User Token у Graph API Explorer '
            'і натисни «Синхронізувати з Meta» у Settings.\n\n'
            '<b>Довготривало:</b> заповни fb_app_id + fb_app_secret у Settings + '
            'увімкни Auto-refresh FB Page tokens — токени автоматично стануть long-lived.',
            silent=False,
        )

    # ── V2 F6: Long-lived token auto-refresh ──────────────────────────────
    @api.model
    def _exchange_token_for_long_lived(self, short_lived_token):
        """
        Обмінює токен на long-lived через Meta Graph /oauth/access_token.
        Повертає (new_token, expires_in) або (None, None) на помилку.
        Потребує fb_app_id + fb_app_secret у ir.config_parameter.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        app_id = ICP.get_param('odoo_chatwoot_connector.fb_app_id', '')
        app_secret = ICP.get_param('odoo_chatwoot_connector.fb_app_secret', '')
        if not (app_id and app_secret and short_lived_token):
            return None, None
        try:
            resp = requests.get(
                'https://graph.facebook.com/v25.0/oauth/access_token',
                params={
                    'grant_type': 'fb_exchange_token',
                    'client_id': app_id,
                    'client_secret': app_secret,
                    'fb_exchange_token': short_lived_token,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                err = self._parse_fb_error(resp)
                _logger.error('SendPulse Odoo: token exchange HTTP %d — %s', resp.status_code, err)
                return None, None
            data = resp.json()
            new_token = data.get('access_token') or ''
            expires_in = data.get('expires_in')  # seconds, або null для безстрокового
            return new_token or None, expires_in
        except Exception as e:
            _logger.error('SendPulse Odoo: token exchange exception — %s', e)
            return None, None

    @api.model
    def cron_refresh_fb_tokens(self):
        """
        Weekly. Для кожного Page де токен помирає < token_refresh_threshold_days днів —
        exchange на long-lived.
        No-op якщо auto_refresh_tokens_enabled=False або app credentials не налаштовані.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if ICP.get_param('odoo_chatwoot_connector.auto_refresh_tokens_enabled', 'False') != 'True':
            return
        app_id = ICP.get_param('odoo_chatwoot_connector.fb_app_id', '')
        app_secret = ICP.get_param('odoo_chatwoot_connector.fb_app_secret', '')
        if not (app_id and app_secret):
            _logger.info('SendPulse Odoo: token refresh skipped — no app_id/secret')
            return
        try:
            threshold_days = int(
                ICP.get_param('odoo_chatwoot_connector.token_refresh_threshold_days', '14')
            )
        except (ValueError, TypeError):
            threshold_days = 14

        Page = self.env['sendpulse.facebook.page'].sudo()
        refreshed = 0
        failed = 0
        for page in Page.search([('active', '=', True)]):
            if not page.access_token:
                continue
            result = self._check_single_fb_token(page.access_token, page.name or page.page_id)
            days_left = result.get('days_left')
            # Exchange тільки якщо знаємо скільки лишилось і мало
            if days_left is None or days_left >= threshold_days:
                continue
            _logger.info(
                'SendPulse Odoo: refreshing token for %s (%d days left)',
                page.name,
                days_left,
            )
            new_token, expires_in = self._exchange_token_for_long_lived(page.access_token)
            if new_token:
                page.write(
                    {
                        'access_token': new_token,
                        'last_checked_at': fields.Datetime.now(),
                    }
                )
                # Одразу перевіряємо новий токен щоб оновити token_status
                new_result = self._check_single_fb_token(new_token, page.name)
                page.write({'token_status': new_result.get('status', 'refreshed')})
                refreshed += 1
                self._notify_telegram(
                    f'🔄 <b>FB Page Token refreshed</b> [{page.name}]\n'
                    f'Новий статус: {new_result.get("status", "valid")}',
                    silent=True,
                )
            else:
                failed += 1
                self._notify_telegram(
                    f'❌ <b>FB Page Token refresh FAILED</b> [{page.name}]\n'
                    f'Потрібна ручна регенерація — токен помре за {days_left}д.',
                    silent=False,
                )
        _logger.info(
            'SendPulse Odoo: cron_refresh_fb_tokens — refreshed %d, failed %d',
            refreshed,
            failed,
        )

    def _hide_comment(self, comment_id, service='facebook', page=None):
        """
        Приховує коментар через Graph API.
        FB: POST /{comment_id} body={'is_hidden': true}
        IG: POST /{comment_id} body={'hide': true}
        Повертає (success: bool, error: str|None).
        """
        token = self._get_fb_page_token(page=page)
        if not token or not comment_id:
            return False, 'token або comment_id відсутні'
        url = f'https://graph.facebook.com/v25.0/{comment_id}'
        payload = (
            {'hide': True, 'access_token': token}
            if service == 'instagram'
            else {'is_hidden': True, 'access_token': token}
        )
        ok, err, _resp = self._fb_post_with_retry(
            url,
            payload,
            label=f'hide-comment {comment_id} ({service})',
        )
        if ok:
            _logger.info('SendPulse Odoo: comment %s hidden (%s)', comment_id, service)
        return ok, err

    def _send_comment_public_reply(self, comment_id, service, text, page=None):
        """
        Публікує публічну відповідь під коментарем через Facebook Graph API.
        Facebook: POST /v25.0/{comment_id}/comments
        Instagram: POST /v25.0/{comment_id}/replies
        page — sendpulse.facebook.page record (опц.). Якщо не задано — fallback на legacy.
        Повертає (success: bool, error: str|None)
        """
        token = self._get_fb_page_token(page=page)
        if not token:
            return (
                False,
                'Page Access Token не налаштований (Налаштування → SendPulse → Facebook Page Access Token, або створіть запис у Facebook Pages)',
            )

        endpoint = 'replies' if service == 'instagram' else 'comments'
        url = f'https://graph.facebook.com/v25.0/{comment_id}/{endpoint}'
        ok, err, _resp = self._fb_post_with_retry(
            url,
            {'message': text, 'access_token': token},
            label=f'public-reply {comment_id}',
        )
        if ok:
            _logger.info('SendPulse Odoo: public reply posted for comment %s', comment_id)
        return ok, err

    def _send_comment_private_reply(self, comment_id, text, service='facebook', page=None):
        """
        Надсилає приватне повідомлення у відповідь на коментар.
        Facebook: POST /{comment_id}/private_replies
        Instagram: POST /{ig-user-id}/messages з recipient.comment_id
        page — sendpulse.facebook.page record (опц.). Для IG використовує page.ig_business_id.
        Повертає (success: bool, error: str|None)
        """
        token = self._get_fb_page_token(page=page)
        if not token:
            return False, 'Page Access Token не налаштований'

        if service == 'instagram':
            # Спочатку пробуємо per-page ig_business_id, потім глобальний fallback
            ig_user_id = (page.ig_business_id if page else False) or self.env[
                'ir.config_parameter'
            ].sudo().get_param('odoo_chatwoot_connector.ig_user_id', '')
            if not ig_user_id:
                return (
                    False,
                    'Instagram Business Account ID не налаштований (ні на Page, ні в глобальних settings)',
                )
            url = f'https://graph.facebook.com/v25.0/{ig_user_id}/messages'
            payload = {
                'recipient': {'comment_id': comment_id},
                'message': {'text': text},
                'access_token': token,
            }
        else:
            url = f'https://graph.facebook.com/v25.0/{comment_id}/private_replies'
            payload = {'message': text, 'access_token': token}

        ok, err, _resp = self._fb_post_with_retry(
            url,
            payload,
            label=f'private-reply {comment_id} ({service})',
        )
        if ok:
            _logger.info(
                'SendPulse Odoo: private reply sent for comment %s (%s)', comment_id, service
            )
        return ok, err

    def _get_fb_page_token(self, page=None):
        """
        Повертає Facebook Page Access Token.

        Пріоритет:
        1. page.access_token — якщо передано Page record з токеном
        2. Page за sp_page_id цієї розмови (self) — для multi-page webhook-ів
        3. Default Page у sendpulse.facebook.page (is_default=True, active=True)
        4. Legacy fallback — `ir.config_parameter.fb_page_access_token`
        """
        if page and page.access_token:
            return page.access_token
        # Якщо self — sendpulse.connect запис з sp_page_id, спробуємо знайти Page
        if self and hasattr(self, 'sp_page_id') and self.sp_page_id:
            Page = self.env['sendpulse.facebook.page'].sudo()
            found = Page.find_by_page_id(self.sp_page_id)
            if found and found.access_token:
                return found.access_token
        # Default Page
        Page = self.env['sendpulse.facebook.page'].sudo()
        default = Page.search([('is_default', '=', True), ('active', '=', True)], limit=1)
        if default and default.access_token:
            return default.access_token
        # Legacy fallback
        return (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('odoo_chatwoot_connector.fb_page_access_token', '')
            or ''
        )

    @api.model
    def cron_check_messenger_windows(self):
        """
        Шукає розмови де Messenger 24h-вікно закривається менш ніж за 2 години.
        Надсилає Telegram-алерт + нотатку у Discuss-канал, позначає sp_window_alert_sent=True
        щоб не повторювати сповіщення.
        """
        now = fields.Datetime.now()
        threshold = now + timedelta(hours=2)
        records = self.search(
            [
                ('sp_messenger_window_expires_at', '!=', False),
                ('sp_messenger_window_expires_at', '<=', threshold),
                ('sp_messenger_window_expires_at', '>', now),
                ('sp_window_alert_sent', '=', False),
                ('stage', '!=', 'close'),
            ]
        )
        for rec in records:
            minutes_left = int((rec.sp_messenger_window_expires_at - now).total_seconds() / 60)
            _logger.info(
                'SendPulse Odoo: window closing in %d min for connect %s (%s)',
                minutes_left,
                rec.id,
                rec.name,
            )
            self._notify_telegram(
                f'⏳ <b>Вікно 24h скоро закриється</b>\n\n'
                f'👤 {rec.name} ({rec._get_service_label()})\n'
                f'⏱ Залишилось: <b>{minutes_left} хв</b>\n\n'
                f'Після цього не зможемо писати клієнту поки він не напише сам.',
                silent=True,
            )
            if rec.channel_id:
                rec.channel_id.sudo().with_context(sendpulse_incoming=True).message_post(
                    body=Markup(  # noqa: S704 internal int, no user input
                        f'⏳ <b>Вікно 24h закривається за {minutes_left} хв.</b> '
                        f'Якщо потрібно — напишіть клієнту зараз.'
                    ),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            rec.write({'sp_window_alert_sent': True})

    @api.model
    def _check_single_fb_token(self, token, label):
        """
        Перевіряє один Facebook Page Access Token.
        Повертає dict: {valid: bool, status: str, days_left: int|None, error: str|None}.
        При `invalid` — надсилає Telegram-алерт з міткою label (напр. "CampScout" або "legacy").
        """
        if not token:
            return {'valid': False, 'status': 'not_configured', 'days_left': None, 'error': None}
        try:
            resp = requests.get(
                'https://graph.facebook.com/v25.0/me',
                params={'access_token': token, 'fields': 'id,name'},
                timeout=15,
            )
            if resp.status_code != 200:
                err = self._parse_fb_error(resp)
                _logger.error('SendPulse Odoo [%s]: FB token invalid — %s', label, err)
                self._notify_telegram(
                    f'⚠️ <b>FB Page Token НЕДІЙСНИЙ</b> [{label}]\n\n'
                    f'Причина: {err}\n\n'
                    f'Автовідповіді і приватні повідомлення для цієї Page не працюють. '
                    f'Потрібно згенерувати новий токен.'
                )
                return {
                    'valid': False,
                    'status': f'invalid: {err[:100]}',
                    'days_left': None,
                    'error': err,
                }
        except Exception as e:
            _logger.error('SendPulse Odoo [%s]: FB token check failed — %s', label, e)
            return {
                'valid': False,
                'status': f'check_failed: {str(e)[:100]}',
                'days_left': None,
                'error': str(e),
            }

        # /debug_token (якщо є app credentials)
        ICP = self.env['ir.config_parameter'].sudo()
        app_id = ICP.get_param('odoo_chatwoot_connector.fb_app_id', '')
        app_secret = ICP.get_param('odoo_chatwoot_connector.fb_app_secret', '')
        if not (app_id and app_secret):
            return {
                'valid': True,
                'status': 'valid (no app_id/secret for expiry)',
                'days_left': None,
                'error': None,
            }
        try:
            resp = requests.get(
                'https://graph.facebook.com/v25.0/debug_token',
                params={'input_token': token, 'access_token': f'{app_id}|{app_secret}'},
                timeout=15,
            )
            if resp.status_code != 200:
                return {
                    'valid': True,
                    'status': 'valid (debug_token failed)',
                    'days_left': None,
                    'error': None,
                }
            data = resp.json().get('data', {})
            expires_at = data.get('expires_at', 0)
            if expires_at == 0:
                return {
                    'valid': True,
                    'status': 'valid: never expires',
                    'days_left': None,
                    'error': None,
                }
            exp_dt = datetime.utcfromtimestamp(expires_at)
            days_left = (exp_dt - datetime.utcnow()).days
            if days_left < 7:
                _logger.error('SendPulse Odoo [%s]: FB token expires in %d days!', label, days_left)
                self._notify_telegram(
                    f'⚠️ <b>FB Page Token скоро помре</b> [{label}]\n\n'
                    f'Залишилось днів: <b>{days_left}</b>\n'
                    f'Треба згенерувати новий у Business Manager → System Users → Generate Token.'
                )
                return {
                    'valid': True,
                    'status': f'expires_soon: {days_left}d',
                    'days_left': days_left,
                    'error': None,
                }
            return {
                'valid': True,
                'status': f'valid: {days_left}d left',
                'days_left': days_left,
                'error': None,
            }
        except Exception as e:
            _logger.warning('SendPulse Odoo [%s]: debug_token exception — %s', label, e)
            return {
                'valid': True,
                'status': 'valid (debug_token error)',
                'days_left': None,
                'error': None,
            }

    @api.model
    def cron_check_fb_token_expiry(self):
        """
        Щотижнева перевірка токенів. Перевіряє:
        1. Усі записи sendpulse.facebook.page (active=True)
        2. Legacy fb_page_access_token (якщо ще використовується)
        """
        now_iso = fields.Datetime.now()
        ICP = self.env['ir.config_parameter'].sudo()

        # 1. Multi-page токени
        Page = self.env['sendpulse.facebook.page'].sudo()
        for page in Page.search([('active', '=', True)]):
            res = self._check_single_fb_token(page.access_token, page.name or page.page_id)
            page.write(
                {
                    'token_status': res['status'],
                    'last_checked_at': now_iso,
                }
            )

        # 2. Legacy токен (для обратної сумісності — поки не всі міграли на Page records)
        legacy_token = ICP.get_param('odoo_chatwoot_connector.fb_page_access_token', '')
        ICP.set_param('odoo_chatwoot_connector.fb_token_last_check', now_iso.isoformat())
        if legacy_token:
            # Перевіряємо тільки якщо legacy не дублює якусь Page (щоб не слати 2 алерти)
            duplicate = Page.search(
                [('access_token', '=', legacy_token), ('active', '=', True)], limit=1
            )
            if not duplicate:
                res = self._check_single_fb_token(legacy_token, 'legacy fb_page_access_token')
                ICP.set_param('odoo_chatwoot_connector.fb_token_status', res['status'])
                if res.get('days_left') is not None:
                    ICP.set_param(
                        'odoo_chatwoot_connector.fb_token_expires_at',
                        (datetime.utcnow() + timedelta(days=res['days_left'])).isoformat(),
                    )
            else:
                ICP.set_param(
                    'odoo_chatwoot_connector.fb_token_status',
                    f'valid (mirrored by Page "{duplicate.name}")',
                )
        else:
            ICP.set_param('odoo_chatwoot_connector.fb_token_status', 'not_configured')

    @staticmethod
    def _parse_fb_error(resp):
        """Витягує людиночитане повідомлення про помилку з відповіді Graph API."""
        try:
            data = resp.json()
            err = data.get('error', {})
            msg = err.get('message', '') or ''
            code = err.get('code', '')
            subcode = err.get('error_subcode', '')
            parts = [
                p
                for p in [
                    f'код {code}' if code else '',
                    f'підкод {subcode}' if subcode else '',
                    msg,
                ]
                if p
            ]
            return ' — '.join(parts) or resp.text[:200]
        except Exception:
            return resp.text[:200] if resp.text else f'HTTP {resp.status_code}'
