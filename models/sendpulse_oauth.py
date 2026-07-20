import logging
import time

import requests
from odoo import api, models

_logger = logging.getLogger(__name__)

# OAuth кеш (як sendpulse-rest-api-python: один токен до закінчення TTL, не POST на кожен виклик API).
# Перенесено сюди разом з методами (було на верху sendpulse_connect.py) — ці константи
# використовуються ВИНЯТКОВО OAuth-кластером (перевірено grep по всьому файлу
# на момент витягу, інших звернень не було), тому перенесені, а не дубльовані/імпортовані.
_SENDPULSE_OAUTH_TOKEN_PARAM = 'odoo_chatwoot_connector.oauth_access_token'
_SENDPULSE_OAUTH_UNTIL_PARAM = 'odoo_chatwoot_connector.oauth_valid_until'
_SENDPULSE_OAUTH_LOCK_KEY1 = 94219
_SENDPULSE_OAUTH_LOCK_KEY2 = 55817


class SendpulseConnectOAuth(models.Model):
    _inherit = 'sendpulse.connect'

    # ════════════════════════════════════════════════════════════════════
    # SendPulse API — відправка повідомлень
    # ════════════════════════════════════════════════════════════════════

    @api.model
    def _sendpulse_oauth_invalidate_cache(self):
        """Примусово вважати кеш токена простроченим (наприклад після 401 від API)."""
        self.env['ir.config_parameter'].sudo().set_param(_SENDPULSE_OAUTH_UNTIL_PARAM, '0')

    def _sendpulse_oauth_read_cache_db(self):
        """Читає кеш токена з БД (після pg_advisory_xact_lock — актуальні значення від інших воркерів)."""
        self.env.cr.execute(
            'SELECT key, value FROM ir_config_parameter WHERE key IN (%s, %s)',
            (_SENDPULSE_OAUTH_TOKEN_PARAM, _SENDPULSE_OAUTH_UNTIL_PARAM),
        )
        rows = dict(self.env.cr.fetchall())
        return (
            (rows.get(_SENDPULSE_OAUTH_TOKEN_PARAM) or '').strip(),
            (rows.get(_SENDPULSE_OAUTH_UNTIL_PARAM) or '').strip(),
        )

    @api.model
    def _sendpulse_oauth_do_refresh(self):
        """POST oauth/access_token з backoff на 429; зберігає токен і час придатності в ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        client_id = ICP.get_param('odoo_chatwoot_connector.client_id', '')
        client_secret = ICP.get_param('odoo_chatwoot_connector.client_secret', '')
        if not client_id or not client_secret:
            _logger.warning('SendPulse Odoo: не налаштовані client_id / client_secret')
            return None
        max_attempts = 5
        last_err = None
        for attempt in range(max_attempts):
            try:
                resp = requests.post(
                    'https://api.sendpulse.com/oauth/access_token',
                    json={
                        'grant_type': 'client_credentials',
                        'client_id': client_id,
                        'client_secret': client_secret,
                    },
                    timeout=15,
                )
                if resp.status_code == 429:
                    ra = (resp.headers.get('Retry-After') or '').strip()
                    try:
                        wait = float(ra) if ra else None
                    except ValueError:
                        wait = None
                    if wait is None or wait <= 0:
                        wait = min(2.0**attempt, 30.0)
                    _logger.warning(
                        'SendPulse Odoo: OAuth 429 Too Many Requests, sleep %.1fs (attempt %s/%s)',
                        wait,
                        attempt + 1,
                        max_attempts,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json() if resp.content else {}
                token = (data.get('access_token') or '').strip()
                if not token:
                    _logger.error('SendPulse Odoo: у відповіді OAuth немає access_token')
                    return None
                try:
                    expires_in = int(data.get('expires_in') or 3600)
                except (TypeError, ValueError):
                    expires_in = 3600
                # Запас до реального expiry (офіційна рекомендація — не стукати в OAuth щохвилини).
                margin = 120
                valid_until = time.time() + max(expires_in - margin, 60)
                ICP.set_param(_SENDPULSE_OAUTH_TOKEN_PARAM, token)
                ICP.set_param(_SENDPULSE_OAUTH_UNTIL_PARAM, str(valid_until))
                return token
            except Exception as e:
                last_err = e
                _logger.error('SendPulse Odoo: помилка отримання токена: %s', e)
                if attempt < max_attempts - 1:
                    time.sleep(min(2.0**attempt, 10.0))
        if last_err:
            _logger.error(
                'SendPulse Odoo: OAuth після %s спроб не вдався: %s', max_attempts, last_err
            )
        return None

    @api.model
    def _get_access_token(self, force_refresh=False):
        """
        OAuth2 Bearer для SendPulse.
        Кешує токен до закінчення терміну (expires_in від API), щоб уникнути 429 на oauth/access_token.
        Між воркерами Odoo — pg_advisory_xact_lock + повторне читання з БД після очікування.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        now = time.time()
        if not force_refresh:
            token = ICP.get_param(_SENDPULSE_OAUTH_TOKEN_PARAM, '')
            until_s = ICP.get_param(_SENDPULSE_OAUTH_UNTIL_PARAM, '')
            if token and until_s:
                try:
                    if now < float(until_s):
                        return token
                except ValueError:
                    pass
        self.env.cr.execute(
            'SELECT pg_advisory_xact_lock(%s, %s)',
            (_SENDPULSE_OAUTH_LOCK_KEY1, _SENDPULSE_OAUTH_LOCK_KEY2),
        )
        token, until_s = self._sendpulse_oauth_read_cache_db()
        if not force_refresh and token and until_s:
            try:
                if now < float(until_s):
                    return token
            except ValueError:
                pass
        return self._sendpulse_oauth_do_refresh()
