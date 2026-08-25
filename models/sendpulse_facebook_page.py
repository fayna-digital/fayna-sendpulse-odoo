import logging

import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SendpulseFacebookPage(models.Model):
    _name = 'sendpulse.facebook.page'
    _description = 'Facebook Page для автовідповідей'
    _order = 'is_default desc, name'

    # ── Magic-number константи (аудит 19.07.2026, issue #8) ───────────────
    _TOKEN_VERIFY_TIMEOUT = 10  # requests timeout(s) для GET /me (action_verify_token)
    _META_SYNC_TIMEOUT = 15  # requests timeout(s) для GET /me/accounts (sync_from_meta)
    _TOKEN_ERROR_PREVIEW_LEN = 100  # обрізка err/str(e) у token_status полі

    name = fields.Char(string='Назва', required=True)
    page_id = fields.Char(string='Page ID', required=True, index=True)
    access_token = fields.Char(string='Page Access Token', required=True)
    ig_business_id = fields.Char(string='Instagram Business Account ID')
    category = fields.Char(string='Категорія')
    active = fields.Boolean(string='Активна', default=True)
    is_default = fields.Boolean(
        string='За замовчуванням',
        help='Використовується для webhook-ів де page_id не вказано або не знайдено.',
    )
    profile_id = fields.Many2one(
        'meta.profile',
        string='Meta Profile',
        ondelete='set null',
        index=True,
        help='Профіль (User Access Token), з якого синхронізована ця сторінка.',
    )
    last_checked_at = fields.Datetime(string='Остання перевірка токена')
    token_status = fields.Char(string='Статус токена', readonly=True, default='not_checked')

    # Per-page overrides (опційно — інакше беруть глобальні значення)
    landing_url = fields.Char(
        string='Landing URL (override)',
        help='Якщо задано — підставляється як {landing_url} у шаблонах замість глобального.',
    )
    tg_url = fields.Char(string='Telegram URL (override)')
    yt_url = fields.Char(string='YouTube URL (override)')

    _sql_constraints = [
        ('page_id_unique', 'UNIQUE(page_id)', 'Page ID повинен бути унікальним.'),
    ]

    @api.constrains('is_default')
    def _check_single_default(self):
        for rec in self:
            if rec.is_default:
                others = self.search(
                    [
                        ('id', '!=', rec.id),
                        ('is_default', '=', True),
                    ]
                )
                if others:
                    others.write({'is_default': False})

    @api.model
    def find_by_page_id(self, page_id):
        """Знаходить активну Page по page_id. Fallback — default."""
        if not page_id:
            return self.search([('is_default', '=', True), ('active', '=', True)], limit=1)
        page = self.search([('page_id', '=', str(page_id)), ('active', '=', True)], limit=1)
        if page:
            return page
        return self.search([('is_default', '=', True), ('active', '=', True)], limit=1)

    def action_verify_token(self):
        """Перевіряє токен через GET /me — оновлює status."""
        for rec in self:
            if not rec.access_token:
                rec.token_status = 'no_token'
                continue
            try:
                resp = requests.get(
                    f'https://graph.facebook.com/v25.0/{rec.page_id}',
                    params={'access_token': rec.access_token, 'fields': 'id,name'},
                    timeout=self._TOKEN_VERIFY_TIMEOUT,
                )
                if resp.status_code == 200:
                    rec.token_status = 'valid'
                else:
                    err = resp.json().get('error', {}).get('message', f'HTTP {resp.status_code}')
                    rec.token_status = f'invalid: {err[: self._TOKEN_ERROR_PREVIEW_LEN]}'
                rec.last_checked_at = fields.Datetime.now()
            except Exception as e:
                rec.token_status = f'check_failed: {str(e)[: self._TOKEN_ERROR_PREVIEW_LEN]}'
        return True

    @api.model
    def sync_from_meta(self, user_token, profile_id=None):
        """
        Синхронізує Pages з Meta через /me/accounts.
        Створює нові записи і оновлює існуючі (токени, IG business).
        Якщо передано profile_id — прив'язує сторінки до meta.profile.
        Повертає список створених/оноволених сторінок.
        """
        if not user_token:
            raise UserError(_('Потрібен User Access Token з правом pages_show_list.'))
        try:
            resp = requests.get(
                'https://graph.facebook.com/v25.0/me/accounts',
                params={
                    'access_token': user_token,
                    'fields': 'id,name,access_token,instagram_business_account,category',
                    'limit': 100,
                },
                timeout=self._META_SYNC_TIMEOUT,
            )
            if resp.status_code != 200:
                err = resp.json().get('error', {}).get('message', f'HTTP {resp.status_code}')
                raise UserError(_('Meta /me/accounts помилка: %s') % err)
            data = resp.json().get('data', [])
        except UserError:
            raise
        except Exception as e:
            raise UserError(_('Помилка запиту до Meta: %s') % e)

        processed = []
        for item in data:
            pid = str(item.get('id', ''))
            if not pid:
                continue
            ig_id = (item.get('instagram_business_account') or {}).get('id') or False
            vals = {
                'name': item.get('name') or pid,
                'page_id': pid,
                'access_token': item.get('access_token') or '',
                'ig_business_id': ig_id,
                'category': item.get('category') or '',
                'active': True,
            }
            if profile_id:
                vals['profile_id'] = profile_id
            existing = self.search([('page_id', '=', pid)], limit=1)
            if existing:
                existing.write(vals)
                processed.append((existing, 'updated'))
            else:
                new = self.create(vals)
                processed.append((new, 'created'))
        return processed

    def _subscribe_messages_webhook(self):
        """
        Підписує цю Page на webhook з полем `messages` через
        POST /{page_id}/subscribed_apps?subscribed_fields=messages.
        Повертає (ok: bool, error: str|None).
        """
        self.ensure_one()
        if not self.page_id or not self.access_token:
            return False, 'Page ID або access_token відсутній'
        try:
            resp = requests.post(
                f'https://graph.facebook.com/v25.0/{self.page_id}/subscribed_apps',
                params={
                    'access_token': self.access_token,
                    'subscribed_fields': 'messages',
                },
                timeout=self._META_SYNC_TIMEOUT,
            )
            if resp.status_code == 200:
                _logger.info(
                    'Channel Bridge: page %s subscribed to messages webhook',
                    self.page_id,
                )
                return True, None
            err = resp.json().get('error', {}).get('message', f'HTTP {resp.status_code}')
            _logger.warning('Channel Bridge: subscribe failed for page %s — %s', self.page_id, err)
            return False, err
        except Exception as e:
            _logger.error('Channel Bridge: subscribe exception for page %s — %s', self.page_id, e)
            return False, str(e)
