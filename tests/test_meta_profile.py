# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести meta.profile — прив'язка через особистий профіль (User Access Token).

Покриває:
  - meta.profile: action_connect (OAuth URL), action_sync_pages (sync + subscribe)
  - meta.profile._finalize_oauth: code → token → long-lived → /me (мок requests)
  - sendpulse.facebook.page._subscribe_messages_webhook (мок requests)
  - sync_from_meta прив'язує profile_id до сторінок
"""

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


def _mock_resp(status_code=200, payload=None, text=None):
    mock = type('Resp', (), {})()
    mock.status_code = status_code
    mock.text = text or ''
    mock.json = lambda: payload or {}
    return mock


@tagged('post_install', '-at_install')
class MetaProfileTestCase(TransactionCase):
    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        self.ICP = ICP
        ICP.set_param('odoo_chatwoot_connector.fb_app_id', 'TEST_APP_ID')
        ICP.set_param('odoo_chatwoot_connector.fb_app_secret', 'TEST_APP_SECRET')

        self.Profile = self.env['meta.profile'].sudo()
        self.profile = self.Profile.create(
            {'name': 'Test Meta Profile', 'user_id': self.env.user.id}
        )

    def _fake_accounts(self):
        """Payload GET /me/accounts — 2 сторінки, одна з IG."""
        return {
            'data': [
                {
                    'id': 'page_1',
                    'name': 'Page One',
                    'access_token': 'EAAJ_page1',
                    'category': 'Business',
                    'instagram_business_account': {'id': 'ig_1'},
                },
                {
                    'id': 'page_2',
                    'name': 'Page Two',
                    'access_token': 'EAAJ_page2',
                    'category': 'Business',
                },
            ]
        }


class TestMetaProfileOAuth(MetaProfileTestCase):
    def test_action_connect_returns_oauth_url(self):
        """action_connect повертає ir.actions.act_url на Facebook dialog."""
        action = self.profile.action_connect()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertIn('dialog/oauth', action['url'])
        self.assertIn('client_id=TEST_APP_ID', action['url'])
        self.assertIn('redirect_uri=', action['url'])
        self.assertIn('pages_messaging', action['url'])
        self.assertIn('instagram_business_manage_messages', action['url'])

    def test_finalize_oauth_saves_token_and_syncs_pages(self):
        """Повний OAuth callback: code → token → long-lived → /me → sync."""
        # 1. exchange code → short token
        resp_token = _mock_resp(200, {'access_token': 'SHORT_TOKEN', 'expires_in': 5000})
        # 2. long-lived exchange
        resp_long = _mock_resp(200, {'access_token': 'LONG_TOKEN', 'expires_in': 5184000})
        # 3. /me
        resp_me = _mock_resp(200, {'id': 'fb_user_1', 'name': 'Volodymyr'})
        # 4. /me/accounts (sync_from_meta)
        resp_accounts = _mock_resp(200, self._fake_accounts())
        # 5. subscribed_apps x2
        resp_sub = _mock_resp(200, {'success': True})

        with (
            patch(
                'requests.get',
                side_effect=[resp_token, resp_long, resp_me, resp_accounts],
            ),
            patch('requests.post', return_value=resp_sub) as mock_post,
        ):
            ok, err = self.profile._finalize_oauth('AUTH_CODE')

        self.assertTrue(ok, f'finalize should succeed, got err={err}')
        self.profile.invalidate_recordset()
        self.assertEqual(self.profile.user_access_token, 'LONG_TOKEN')
        self.assertEqual(self.profile.fb_user_id, 'fb_user_1')
        self.assertTrue(self.profile.expires_at)
        # 2 сторінки створені, прив'язані до профілю
        self.assertEqual(len(self.profile.page_ids), 2)
        # subscribed_apps викликано двічі (для кожної сторінки)
        self.assertEqual(mock_post.call_count, 2)


class TestFacebookPageSubscribe(MetaProfileTestCase):
    def test_subscribe_messages_webhook_success(self):
        """_subscribe_messages_webhook POST /subscribed_apps з subscribed_fields=messages."""
        Page = self.env['sendpulse.facebook.page'].sudo()
        page = Page.create({'name': 'Page One', 'page_id': 'page_1', 'access_token': 'EAAJ_page1'})
        resp = _mock_resp(200, {'success': True})
        with patch('requests.post', return_value=resp) as mock_post:
            ok, err = page._subscribe_messages_webhook()
        self.assertTrue(ok)
        self.assertIsNone(err)
        args, kwargs = mock_post.call_args
        self.assertIn('/page_1/subscribed_apps', args[0])
        self.assertEqual(kwargs['params']['subscribed_fields'], 'messages')
        self.assertEqual(kwargs['params']['access_token'], 'EAAJ_page1')

    def test_subscribe_messages_webhook_failure(self):
        """При помилці Meta повертає (False, err)."""
        Page = self.env['sendpulse.facebook.page'].sudo()
        page = Page.create({'name': 'Page One', 'page_id': 'page_1', 'access_token': 'EAAJ_page1'})
        resp = _mock_resp(
            400,
            {'error': {'message': 'Invalid token'}},
            text='{"error":{"message":"Invalid token"}}',
        )
        with patch('requests.post', return_value=resp):
            ok, err = page._subscribe_messages_webhook()
        self.assertFalse(ok)
        self.assertIn('Invalid token', err)


class TestSyncFromMeta(MetaProfileTestCase):
    def test_sync_from_meta_binds_profile(self):
        """sync_from_meta з profile_id прив'язує створені сторінки."""
        resp = _mock_resp(200, self._fake_accounts())
        with patch('requests.get', return_value=resp):
            processed = (
                self.env['sendpulse.facebook.page']
                .sudo()
                .sync_from_meta('USER_TOKEN', profile_id=self.profile.id)
            )
        self.assertEqual(len(processed), 2)
        created = [p for p, a in processed if a == 'created']
        self.assertEqual(len(created), 2)
        for page in created:
            self.assertEqual(page.profile_id.id, self.profile.id)
