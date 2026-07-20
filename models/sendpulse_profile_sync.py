import base64
import logging

import requests
from odoo import _, models

_logger = logging.getLogger(__name__)


class SendpulseConnectProfileSync(models.Model):
    _inherit = 'sendpulse.connect'

    # ════════════════════════════════════════════════════════════════════
    # SendPulse API — синхронізація профілю контакту (Priority 3)
    # ════════════════════════════════════════════════════════════════════

    # Ендпоінти GET-контакту по сервісу
    _CONTACT_GET_ENDPOINTS = {
        'telegram': 'https://api.sendpulse.com/telegram/contacts/get',
        'instagram': 'https://api.sendpulse.com/instagram/contacts/get',
        'facebook': 'https://api.sendpulse.com/facebook/contacts/get',
        'messenger': 'https://api.sendpulse.com/messenger/contacts/get',
        'viber': 'https://api.sendpulse.com/viber/contacts/get',
        'whatsapp': 'https://api.sendpulse.com/whatsapp/contacts/get',
        'tiktok': 'https://api.sendpulse.com/tiktok/contacts/get',
    }

    _SP_STATUS_MAP = {
        'active': 'active',
        'unsubscribed': 'unsubscribed',
        'deleted': 'deleted',
        'unconfirmed': 'unconfirmed',
    }

    def action_fetch_contact_info(self):
        """
        Отримує актуальні дані контакту з SendPulse API:
        avatar, мова, статус підписки, bot-змінні.
        Викликається вручну з форми розмови (кнопка "Оновити профіль").
        """
        self.ensure_one()
        if not self.sendpulse_contact_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'SendPulse',
                    'message': _('Немає contact_id'),
                    'type': 'warning',
                },
            }

        token = self._get_access_token()
        if not token:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'SendPulse',
                    'message': _('Не вдалося отримати токен API'),
                    'type': 'danger',
                },
            }

        endpoint = self._CONTACT_GET_ENDPOINTS.get(
            self.service or 'telegram', self._CONTACT_GET_ENDPOINTS['telegram']
        )
        try:
            resp = requests.get(
                endpoint,
                params={'id': self.sendpulse_contact_id},
                headers={'Authorization': f'Bearer {token}'},
                timeout=10,
            )
            if resp.status_code == 401:
                self._sendpulse_oauth_invalidate_cache()
                token = self._get_access_token(force_refresh=True)
                if token:
                    resp = requests.get(
                        endpoint,
                        params={'id': self.sendpulse_contact_id},
                        headers={'Authorization': f'Bearer {token}'},
                        timeout=10,
                    )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            _logger.warning(
                'SendPulse Odoo: не вдалося отримати профіль %s: %s', self.sendpulse_contact_id, e
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': 'SendPulse', 'message': f'Помилка API: {e}', 'type': 'danger'},
            }

        vals = self._extract_contact_vals(data)
        if vals:
            self.write(vals)
            _logger.info(
                'SendPulse Odoo: профіль %s оновлено, поля: %s',
                self.sendpulse_contact_id,
                list(vals.keys()),
            )

        # Синхронізуємо аватар у картку партнера якщо він ідентифікований
        if self.partner_id and self.avatar_url:
            self._sync_avatar_to_partner()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': 'SendPulse', 'message': _('Профіль оновлено'), 'type': 'success'},
        }

    def _sync_avatar_to_partner(self):
        """
        Завантажує фото з avatar_url і зберігає в картці Odoo-партнера (image_1920).
        Викликається після action_fetch_contact_info якщо партнер ідентифікований.
        Не перезаписує фото якщо URL не змінився (порівнюємо розмір).
        """
        self.ensure_one()
        if not self.partner_id or not self.avatar_url:
            return
        try:
            resp = requests.get(self.avatar_url, timeout=15)
            resp.raise_for_status()
            image_b64 = base64.b64encode(resp.content).decode()
            self.partner_id.write({'image_1920': image_b64})
            _logger.info('SendPulse Odoo: аватар партнера %s оновлено', self.partner_id.name)
        except Exception as e:
            _logger.warning(
                'SendPulse Odoo: не вдалося завантажити аватар %s: %s', self.avatar_url, e
            )

    # GET /contacts/get: status — ціле число: 1=active, 0=unsubscribed, 2=deleted, 3=unconfirmed
    _SP_STATUS_INT_MAP = {1: 'active', 0: 'unsubscribed', 2: 'deleted', 3: 'unconfirmed'}

    def _extract_contact_vals(self, data):
        """
        Витягує поля з відповіді SendPulse GET /contacts/get.

        Реальна структура відповіді:
          {"success": true, "data": {
              "status": 1,
              "channel_data": {
                  "photo": "https://...",        (Telegram — може бути null)
                  "profile_pic": "https://...",  (Instagram)
                  "language_code": "uk",
                  "username": "...",
                  "name": "...",
              },
              "variables": {"user_email": "...", ...},
          }}
        """
        contact = data.get('data') if isinstance(data.get('data'), dict) else data
        channel_data = contact.get('channel_data') or {}

        vals = {}

        # Фото: Telegram/WA → channel_data.photo, Instagram → channel_data.profile_pic,
        # Messenger/FB → data.avatar.path
        avatar_obj = contact.get('avatar')
        avatar_path = avatar_obj.get('path') if isinstance(avatar_obj, dict) else None
        photo_url = (
            channel_data.get('photo')
            or channel_data.get('profile_pic')
            or avatar_path
            or contact.get('photo')
        )
        if photo_url and isinstance(photo_url, str) and photo_url.startswith('http'):
            vals['avatar_url'] = photo_url

        # Мова — в channel_data
        lang = (
            channel_data.get('language_code')
            or channel_data.get('language')
            or contact.get('language_code')
            or contact.get('language')
        )
        if lang:
            vals['language_code'] = str(lang)

        # Статус — число або рядок
        raw_status = contact.get('status')
        if isinstance(raw_status, int):
            mapped_status = self._SP_STATUS_INT_MAP.get(raw_status)
        else:
            mapped_status = self._SP_STATUS_MAP.get((raw_status or '').lower())
        if mapped_status:
            vals['subscription_status'] = mapped_status

        # Bot-змінні
        variables = contact.get('variables') or {}
        if isinstance(variables, list):
            variables = {v['name']: v.get('value', '') for v in variables if v.get('name')}

        child_name = (variables.get('child_name') or '').strip()
        if child_name and not self.sp_child_name:
            vals['sp_child_name'] = child_name

        booking_email = (variables.get('booking_email') or '').strip()
        if booking_email and not self.sp_booking_email:
            vals['sp_booking_email'] = booking_email

        _logger.info('SendPulse Odoo: extracted vals keys=%s', list(vals.keys()))
        return vals
