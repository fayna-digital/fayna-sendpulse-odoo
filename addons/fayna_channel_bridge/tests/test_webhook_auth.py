# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Б-1 (F-03 P0): HMAC-автентифікація вебхуків.

Покриває:
  - T-10: POST з валідним підписом → 200 і запис створено
  - T-11: POST без підпису → 401 і жодного запису
  - T-15: POST з невалідним підписом → 401 і жодного запису
"""

import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged

from ..controllers.main import ChannelBridgeController


def _sign(body, secret):
    """Повертає Meta-стиль підпису ``sha256=<hex>`` для сирого тіла."""
    digest = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return f'sha256={digest}'


@tagged('post_install', '-at_install')
class TestWebhookAuth(HttpCase):
    """Б-1: вебхуки відхиляють запити без валідного HMAC-підпису."""

    def setUp(self):
        super().setUp()
        self.backend = self.env['channel.backend'].create(
            {
                'name': 'MSG Auth Page',
                'service': 'messenger',
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': 'app_secret_123',
            }
        )
        self.secret = 'app_secret_123'

    def _messenger_payload(self):
        return {
            'object': 'page',
            'entry': [
                {
                    'id': '123',
                    'messaging': [
                        {
                            'sender': {'id': 'psid_1'},
                            'message': {'mid': 'm_1', 'text': 'Привіт'},
                        }
                    ],
                }
            ],
        }

    def _post(self, body, headers):
        return self.url_open(
            '/bridge/messenger/webhook',
            data=body,
            headers=headers,
        )

    def _incoming_count(self):
        return self.env['channel.message'].search_count(
            [('service', '=', 'messenger'), ('direction', '=', 'incoming')]
        )

    def test_valid_signature_creates_record(self):
        """T-10: валідний X-Hub-Signature-256 → 200 і запис створено."""
        body = json.dumps(self._messenger_payload()).encode('utf-8')
        r = self._post(
            body,
            {
                'Content-Type': 'application/json',
                'X-Hub-Signature-256': _sign(body, self.secret),
            },
        )
        self.assertEqual(r.status_code, 200, 'валідний підпис має дати 200')
        self.assertEqual(self._incoming_count(), 1, 'запис має бути створено')

    def test_missing_signature_rejected(self):
        """T-11: без підпису → 401 і жодного запису."""
        body = json.dumps(self._messenger_payload()).encode('utf-8')
        r = self._post(body, {'Content-Type': 'application/json'})
        self.assertEqual(r.status_code, 401, 'без підпису має бути 401')
        self.assertEqual(self._incoming_count(), 0, 'жодного запису не має бути')

    def test_invalid_signature_rejected(self):
        """T-15: невалідний підпис → 401 і жодного запису."""
        body = json.dumps(self._messenger_payload()).encode('utf-8')
        r = self._post(
            body,
            {
                'Content-Type': 'application/json',
                'X-Hub-Signature-256': _sign(body, 'wrong_secret'),
            },
        )
        self.assertEqual(r.status_code, 401, 'невалідний підпис має дати 401')
        self.assertEqual(self._incoming_count(), 0, 'жодного запису не має бути')

    def test_signature_without_prefix_rejected(self):
        """Б-1.1: підпис без префікса sha256= → 401 до обчислення HMAC."""
        body = json.dumps(self._messenger_payload()).encode('utf-8')
        digest = hmac.new(self.secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
        r = self._post(
            body,
            {
                'Content-Type': 'application/json',
                'X-Hub-Signature-256': digest,  # без 'sha256='
            },
        )
        self.assertEqual(r.status_code, 401, 'підпис без префікса має дати 401')
        self.assertEqual(self._incoming_count(), 0, 'жодного запису не має бути')

    def test_truncated_signature_rejected(self):
        """Б-1.1: правильний префікс, але обрізаний підпис → 401 до обчислення HMAC."""
        body = json.dumps(self._messenger_payload()).encode('utf-8')
        full = _sign(body, self.secret)
        truncated = full[:20]  # 'sha256=' + лише частина hex
        r = self._post(
            body,
            {
                'Content-Type': 'application/json',
                'X-Hub-Signature-256': truncated,
            },
        )
        self.assertEqual(r.status_code, 401, 'обрізаний підпис має дати 401')
        self.assertEqual(self._incoming_count(), 0, 'жодного запису не має бути')

    def test_meta_signature_format_helper(self):
        """Б-1.1: юніт-перевірка формату підпису Meta (sha256= + 64 hex = 71 символ)."""
        controller = ChannelBridgeController()
        # валідний формат
        self.assertTrue(controller._is_valid_meta_signature('sha256=' + 'a' * 64))
        # без префікса
        self.assertFalse(controller._is_valid_meta_signature('a' * 64))
        # обрізаний
        self.assertFalse(controller._is_valid_meta_signature('sha256=' + 'a' * 10))
        # задовгий
        self.assertFalse(controller._is_valid_meta_signature('sha256=' + 'a' * 65))
        # порожній / None
        self.assertFalse(controller._is_valid_meta_signature(''))
        self.assertFalse(controller._is_valid_meta_signature(None))
