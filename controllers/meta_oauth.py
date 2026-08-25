import logging

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class MetaOAuthController(http.Controller):
    """
    OAuth callback для прив'язки особистого профілю Meta (User Access Token).

    Flow:
      1. Користувач натискає «Підключити профіль» на meta.profile →
         redirect на Facebook Login dialog (action_connect).
      2. Meta редиректить сюди з ?code=...&state=<profile_id>.
      3. Обмінюємо code → User Access Token → long-lived → /me → зберігаємо
         у meta.profile і авто-синкуємо сторінки + підписуємо webhook.
    """

    @http.route(
        '/bridge/meta/oauth/callback',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def oauth_callback(self, **kwargs):
        code = kwargs.get('code', '')
        state = kwargs.get('state', '')
        error = kwargs.get('error', '')
        error_reason = kwargs.get('error_reason', '')

        if error:
            _logger.warning('Meta OAuth error: %s (%s) state=%s', error, error_reason, state)
            return self._html(
                'Помилка підключення Meta',
                f'Facebook повернув помилку: {error} — {error_reason}. Спробуйте ще раз.',
            )

        if not state or not state.isdigit():
            _logger.warning('Meta OAuth: invalid state=%r', state)
            return self._html('Помилка', 'Невірний state (id профілю).')

        Profile = request.env['meta.profile'].sudo()
        profile = Profile.browse(int(state)).exists()
        if not profile:
            _logger.warning('Meta OAuth: profile %s not found', state)
            return self._html('Помилка', 'Профіль не знайдено.')

        if not code:
            _logger.warning('Meta OAuth: no code for profile %s', state)
            return self._html('Помилка', 'Meta не повернув code авторизації.')

        ok, err = profile._finalize_oauth(code)
        if not ok:
            _logger.error('Meta OAuth: finalize failed for profile %s — %s', state, err)
            return self._html('Помилка підключення', err)

        _logger.info('Meta OAuth: profile %s connected successfully', state)
        return self._html(
            'Профіль підключено',
            'Профіль Meta успішно підключено. Сторінки синхронізовано і '
            'webhook підписано. Можна закрити цю вкладку.',
            success=True,
        )

    def _html(self, title, message, success=False):
        color = '#2e7d32' if success else '#c62828'
        return Response(
            f"""<!DOCTYPE html>
<html lang="uk">
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;
             background:#f5f5f5;display:flex;align-items:center;
             justify-content:center;height:100vh;margin:0;">
  <div style="background:#fff;padding:40px;border-radius:12px;
              box-shadow:0 2px 12px rgba(0,0,0,.1);max-width:480px;
              text-align:center;">
    <div style="font-size:48px;margin-bottom:16px;">{'✅' if success else '⚠️'}</div>
    <h2 style="margin:0 0 12px;color:#222;">{title}</h2>
    <p style="color:#555;line-height:1.5;">{message}</p>
  </div>
</body></html>""",
            content_type='text/html',
        )
