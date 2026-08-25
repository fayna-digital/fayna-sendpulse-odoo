import logging
from datetime import timedelta

import requests
from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MetaProfile(models.Model):
    """
    Прив'язка через особистий профіль (User Access Token).

    Один запис = один Facebook-користувач, чий User Access Token дає доступ
    до ВСІХ його сторінок (як у SendPulse). Після OAuth-підключення
    `action_sync_pages()` синхронізує сторінки через /me/accounts і
    автоматично підписує webhook (subscribed_fields=messages) на кожну.

    Токен зберігається у полі `user_access_token` (password=True → не
    показується в UI). Секрети застосунку (fb_app_id/fb_app_secret) —
    у ir.config_parameter через Settings.
    """

    _name = 'meta.profile'
    _description = 'Meta Profile (User Access Token)'
    _order = 'name'

    # ── Magic-number константи ───────────────────────────────────────────
    _GRAPH_VERSION = 'v25.0'
    _GRAPH_API = 'https://graph.facebook.com'
    _OAUTH_DIALOG = 'https://www.facebook.com/v25.0/dialog/oauth'
    _TIMEOUT = 15  # requests timeout(s)
    _OAUTH_SCOPE = (
        'pages_show_list,pages_messaging,business_management,instagram_business_manage_messages'
    )

    name = fields.Char(string='Назва', required=True)
    user_id = fields.Many2one(
        'res.users',
        string='Odoo User',
        required=True,
        default=lambda self: self.env.user,
        help='Користувач Odoo, якому належить цей профіль.',
    )
    fb_user_id = fields.Char(string='Facebook User ID')
    user_access_token = fields.Char(
        string='User Access Token',
        password=True,
        help='User Access Token з Facebook Login. Зберігається зашифровано.',
    )
    expires_at = fields.Datetime(string='Термін дії токена')
    page_ids = fields.One2many(
        'sendpulse.facebook.page',
        'profile_id',
        string='Pages',
        help='Сторінки, синхронізовані з цього профілю.',
    )
    active = fields.Boolean(string='Активний', default=True)
    last_sync_at = fields.Datetime(string='Остання синхронізація')

    # ════════════════════════════════════════════════════════════════════
    # Helpers
    # ════════════════════════════════════════════════════════════════════

    def _get_app_credentials(self):
        """Повертає (fb_app_id, fb_app_secret) з ir.config_parameter."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        return (
            ICP.get_param('odoo_chatwoot_connector.fb_app_id', ''),
            ICP.get_param('odoo_chatwoot_connector.fb_app_secret', ''),
        )

    def _get_redirect_uri(self):
        """Callback URL для OAuth (має збігатися з Valid OAuth Redirect URI у Meta)."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        return f'{base_url}/bridge/meta/oauth/callback'

    # ════════════════════════════════════════════════════════════════════
    # OAuth flow
    # ════════════════════════════════════════════════════════════════════

    def action_connect(self):
        """
        Кнопка «Підключити профіль» — redirect на Facebook Login dialog.
        Після авторизації Meta редиректить на /bridge/meta/oauth/callback
        з code + state (id профілю).
        """
        self.ensure_one()
        app_id, _secret = self._get_app_credentials()
        if not app_id:
            raise UserError(_('Заповніть Facebook App ID у Settings (SendPulse Odoo → Meta).'))
        redirect_uri = self._get_redirect_uri()
        url = (
            f'{self._OAUTH_DIALOG}?client_id={app_id}'
            f'&redirect_uri={redirect_uri}'
            f'&state={self.id}'
            f'&scope={self._OAUTH_SCOPE}'
        )
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'self',
        }

    def action_sync_pages(self):
        """
        Кнопка «Синхронізувати сторінки» — викликає sync_from_meta(user_token)
        і підписує webhook (subscribed_fields=messages) на всі сторінки.
        """
        self.ensure_one()
        if not self.user_access_token:
            raise UserError(_('Спершу підключіть профіль (User Access Token).'))
        Page = self.env['sendpulse.facebook.page'].sudo()
        processed = Page.sync_from_meta(self.user_access_token)
        subscribed = 0
        failed = 0
        for page, _action in processed:
            ok, err = page._subscribe_messages_webhook()
            if ok:
                subscribed += 1
            else:
                failed += 1
                _logger.warning(
                    'Meta Profile %s: webhook subscribe failed for page %s — %s',
                    self.id,
                    page.page_id,
                    err,
                )
        self.write({'last_sync_at': fields.Datetime.now()})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Синхронізація завершена'),
                'message': _('Сторінок: %d, webhook підписано: %d, помилок: %d')
                % (len(processed), subscribed, failed),
                'type': 'success' if not failed else 'warning',
                'sticky': False,
            },
        }

    # ════════════════════════════════════════════════════════════════════
    # OAuth callback helpers (викликаються з контролера)
    # ════════════════════════════════════════════════════════════════════

    def _exchange_code_for_token(self, code):
        """
        Обмінює OAuth `code` на User Access Token.
        Повертає (token, expires_in) або (None, None) на помилку.
        """
        self.ensure_one()
        app_id, app_secret = self._get_app_credentials()
        if not (app_id and app_secret and code):
            return None, None
        try:
            resp = requests.get(
                f'{self._GRAPH_API}/{self._GRAPH_VERSION}/oauth/access_token',
                params={
                    'client_id': app_id,
                    'client_secret': app_secret,
                    'redirect_uri': self._get_redirect_uri(),
                    'code': code,
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                _logger.error(
                    'Meta Profile: token exchange HTTP %d — %s',
                    resp.status_code,
                    resp.text[:200],
                )
                return None, None
            data = resp.json()
            token = data.get('access_token') or ''
            expires_in = data.get('expires_in')  # seconds, або null
            return token or None, expires_in
        except Exception as e:
            _logger.error('Meta Profile: token exchange exception — %s', e)
            return None, None

    def _exchange_long_lived(self, short_token):
        """
        Обмінює короткоживучий токен на long-lived через fb_exchange_token.
        Повертає (new_token, expires_in) або (None, None).
        """
        self.ensure_one()
        app_id, app_secret = self._get_app_credentials()
        if not (app_id and app_secret and short_token):
            return None, None
        try:
            resp = requests.get(
                f'{self._GRAPH_API}/{self._GRAPH_VERSION}/oauth/access_token',
                params={
                    'grant_type': 'fb_exchange_token',
                    'client_id': app_id,
                    'client_secret': app_secret,
                    'fb_exchange_token': short_token,
                },
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                _logger.error(
                    'Meta Profile: long-lived exchange HTTP %d — %s',
                    resp.status_code,
                    resp.text[:200],
                )
                return None, None
            data = resp.json()
            new_token = data.get('access_token') or ''
            expires_in = data.get('expires_in')
            return new_token or None, expires_in
        except Exception as e:
            _logger.error('Meta Profile: long-lived exchange exception — %s', e)
            return None, None

    def _fetch_me(self, token):
        """Повертає (fb_user_id, name) через GET /me."""
        self.ensure_one()
        try:
            resp = requests.get(
                f'{self._GRAPH_API}/{self._GRAPH_VERSION}/me',
                params={'access_token': token, 'fields': 'id,name'},
                timeout=self._TIMEOUT,
            )
            if resp.status_code != 200:
                return None, None
            data = resp.json()
            return data.get('id'), data.get('name')
        except Exception as e:
            _logger.error('Meta Profile: /me exception — %s', e)
            return None, None

    def _finalize_oauth(self, code):
        """
        Повний OAuth callback: code → token → long-lived → /me → збереження.
        Повертає (ok: bool, error: str|None).
        """
        self.ensure_one()
        token, expires_in = self._exchange_code_for_token(code)
        if not token:
            return False, 'Не вдалося обміняти code на токен'
        # Long-lived
        long_token, long_expires = self._exchange_long_lived(token)
        final_token = long_token or token
        expires_at = False
        if long_expires:
            expires_at = fields.Datetime.now() + timedelta(seconds=long_expires)
        elif expires_in:
            expires_at = fields.Datetime.now() + timedelta(seconds=expires_in)
        fb_user_id, name = self._fetch_me(final_token)
        self.write(
            {
                'user_access_token': final_token,
                'fb_user_id': fb_user_id or self.fb_user_id,
                'name': name or self.name,
                'expires_at': expires_at,
            }
        )
        # Авто-синк сторінок + підписка webhook
        try:
            self.action_sync_pages()
        except Exception as e:
            _logger.warning('Meta Profile %s: auto-sync after OAuth failed — %s', self.id, e)
        return True, None
