import hashlib
import hmac
import json
from unittest.mock import Mock, patch

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestOperatorEndToEnd(HttpCase):
    """Тест T-01: наскрізний потік оператора через вебхук Telegram."""

    def setUp(self):
        super().setUp()
        backend = self.env['channel.backend'].create(
            {
                'name': 'TG',
                'service': 'telegram',
                'provider': 'direct',
                'transport_priority': 'own',
                'bot_token': '123:TOK',
                'bot_id': '@Bot',
                'webhook_secret': 'tg_secret_123',
                'user_ids': [(6, 0, [self.env.ref('base.user_admin').id])],
            }
        )
        self.backend = backend
        self.officer = self.env.ref('fayna_channel_bridge.group_channel_bridge_officer')

    @staticmethod
    def _tg_ok(status=200, message_id=777):
        resp = Mock()
        resp.status_code = status
        resp.text = '{"ok": true}'
        resp.json.return_value = {'ok': True, 'result': {'message_id': message_id}}
        return resp

    def _incoming(self, text, mid=100, uid=12345):
        payload = {
            'update_id': mid,
            'message': {
                'message_id': mid,
                'date': 1756500000,
                'chat': {'id': uid},
                'from': {'first_name': 'Клієнт'},
                'text': text,
            },
        }
        url = f'/bridge/telegram/webhook/{self.backend.webhook_path_id}'
        r = self.url_open(
            url,
            data=json.dumps(payload),
            headers={
                'Content-Type': 'application/json',
                'X-Telegram-Bot-Api-Secret-Token': self.backend.webhook_secret,
            },
        )
        self.assertEqual(r.status_code, 200, 'webhook має відповісти 200')
        conv = self.env['channel.conversation'].search(
            [('provider_user_id', '=', str(uid))], limit=1
        )
        return conv

    def test_full_operator_flow(self):
        """T-01: end-to-end operator flow."""
        # 1. Incoming message creates conversation
        conv = self._incoming('Потрібна допомога')
        self.assertTrue(conv, 'розмову має бути створено вебхуком')
        # 2. Conversation bound to a channel
        self.assertTrue(conv.channel_id)
        # F-01: operator becomes a member of the discuss channel
        members = self.env['discuss.channel.member'].search_count(
            [('channel_id', '=', conv.channel_id.id)]
        )
        self.assertGreater(members, 0, 'F-01: оператор має бути учасником каналу')
        # F-04: exactly one incoming message logged
        n = self.env['channel.message'].search_count(
            [('provider_message_id', '=', '100'), ('direction', '=', 'incoming')]
        )
        self.assertEqual(n, 1, 'F-04: один webhook = один рядок журналу')
        # F-02: operator replies, outgoing message sent via transport
        with patch('requests.post') as mock:
            mock.return_value = self._tg_ok(200)
            conv.channel_id.with_user(self.env.ref('base.user_admin')).message_post(
                body='<p>Відповідь</p>',
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
        # Check outgoing message record
        sent = self.env['channel.message'].search(
            [('direction', '=', 'outgoing'), ('text_message', '=', 'Відповідь')]
        )
        self.assertEqual(len(sent), 1, 'F-02: рівно одне вихідне')
        self.assertEqual(sent.state, 'sent', 'F-02: стан вихідного повідомлення')
        # Ensure transport was called
        self.assertTrue(mock.called, 'F-02: транспорт має отримати виклик')

    def _post_note(self, **extra):
        """Постить повідомлення-нотатку в канал розмови."""
        conv = self._incoming('Нотатка')
        self.assertTrue(conv, 'розмову має бути створено вебхуком')
        with patch('requests.post') as mock:
            mock.return_value = self._tg_ok(200)
            conv.channel_id.with_user(self.env.ref('base.user_admin')).message_post(
                body='<p>Нотатка</p>',
                message_type='comment',
                **extra,
            )
        return conv

    def test_note_subtype_xmlid_not_sent(self):
        """Б-7: mail.mt_note через subtype_xmlid не йде в транспорт."""
        self._post_note(subtype_xmlid='mail.mt_note')
        n = self.env['channel.message'].search_count(
            [('direction', '=', 'outgoing'), ('text_message', '=', 'Нотатка')]
        )
        self.assertEqual(n, 0, 'Б-7: нотатка (subtype_xmlid) не має йти в транспорт')

    def test_note_subtype_id_not_sent(self):
        """Б-7: mail.mt_note через числовий subtype_id не йде в транспорт."""
        note = self.env.ref('mail.mt_note', raise_if_not_found=False)
        self.assertTrue(note, 'mail.mt_note має існувати')
        self._post_note(subtype_id=note.id)
        n = self.env['channel.message'].search_count(
            [('direction', '=', 'outgoing'), ('text_message', '=', 'Нотатка')]
        )
        self.assertEqual(n, 0, 'Б-7: нотатка (subtype_id) не має йти в транспорт')

    def _telegram_payload(self, mid=200, uid=54321):
        return {
            'update_id': mid,
            'message': {
                'message_id': mid,
                'date': 1756500000,
                'chat': {'id': uid},
                'from': {'first_name': 'Клієнт'},
                'text': 'Привіт',
            },
        }

    def test_telegram_invalid_secret_token(self):
        """Б-2: правильний шлях, але невалідний secret_token → 401 і без запису."""
        url = f'/bridge/telegram/webhook/{self.backend.webhook_path_id}'
        r = self.url_open(
            url,
            data=json.dumps(self._telegram_payload()),
            headers={
                'Content-Type': 'application/json',
                'X-Telegram-Bot-Api-Secret-Token': 'wrong_secret',
            },
        )
        self.assertEqual(r.status_code, 401, 'невалідний secret_token має дати 401')
        n = self.env['channel.message'].search_count(
            [('direction', '=', 'incoming'), ('service', '=', 'telegram')]
        )
        self.assertEqual(n, 0, 'невалідний secret_token не має створювати записів')

    def test_telegram_missing_secret_token(self):
        """Б-2: правильний шлях, але заголовок відсутній → 401 і без запису."""
        url = f'/bridge/telegram/webhook/{self.backend.webhook_path_id}'
        r = self.url_open(
            url,
            data=json.dumps(self._telegram_payload()),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(r.status_code, 401, 'відсутній secret_token має дати 401')
        n = self.env['channel.message'].search_count(
            [('direction', '=', 'incoming'), ('service', '=', 'telegram')]
        )
        self.assertEqual(n, 0, 'відсутній secret_token не має створювати записів')

    def test_exception_text_masks_token(self):
        """Б-3: текст винятку з токеном у last_error маскується на ***."""
        token = self.backend._get_telegram_token()
        self.assertTrue(token, 'має бути налаштований токен')

        # Мок кидає виняток, текст якого містить повний URL з токеном.
        def _boom(*args, **kwargs):
            raise ConnectionError(
                f'https://api.telegram.org/bot{token}/sendMessage failed: timeout'
            )

        with patch('requests.post', side_effect=_boom):
            ok, _msg_id, err = self.backend.send_message(
                'Тест маскування', provider_user_id='12345'
            )
        self.assertFalse(ok, 'транспорт має впасти')
        self.assertIsNotNone(err, 'має бути повернута помилка')
        self.assertNotIn(token, err, 'Б-3: токен не має бути в повернутій помилці')
        self.assertIn('***', err, 'Б-3: помилка має містити маску ***')
        # last_error у БД також не має містити токен.
        self.backend.write({'last_error': err})
        self.assertNotIn(token, self.backend.last_error, 'Б-3: токен не має бути в last_error')
        self.assertIn('***', self.backend.last_error, 'Б-3: last_error має маску ***')

    def _viber_webhook(self, viber, sender_id, text):
        """Надсилає Viber webhook через HTTP з порожнім message.token.

        Використовуємо реальний HTTP-шлях (url_open), як і решта тестів
        класу, щоб не викликати _process_incoming напряму (той відкриває
        власний savepoint і лишає транзакцію в стані, що ламає наступні
        savepoint-тести, напр. test_unique_index_blocks_duplicate).
        """
        payload = {
            'event': 'message',
            'timestamp': 1756500000,
            'sender': {'id': sender_id, 'name': 'Клієнт'},
            'message': {'type': 'text', 'text': text, 'token': ''},
        }
        raw = json.dumps(payload).encode('utf-8')
        signature = hmac.new(
            viber._get_viber_token().encode('utf-8'), raw, hashlib.sha256
        ).hexdigest()
        return self.url_open(
            '/bridge/viber/webhook',
            data=raw,
            headers={
                'Content-Type': 'application/json',
                'X-Viber-Content-Signature': signature,
            },
        )

    def test_empty_provider_message_id_not_deduped(self):
        """Б-6: два вхідні з порожнім provider_message_id → два окремі записи."""
        viber = self.env['channel.backend'].create(
            {
                'name': 'Viber',
                'service': 'viber',
                'provider': 'direct',
                'transport_priority': 'own',
                'webhook_secret': 'viber_secret_123',
                'credentials': json.dumps({'auth_token': 'viber_auth_123'}),
                'user_ids': [(6, 0, [self.env.ref('base.user_admin').id])],
            }
        )
        # Два різні клієнти, обидва без ідентифікатора повідомлення.
        r1 = self._viber_webhook(viber, 'viber_user_1', 'Перше')
        r2 = self._viber_webhook(viber, 'viber_user_2', 'Друге')
        self.assertEqual(r1.status_code, 200, 'перший webhook має відповісти 200')
        self.assertEqual(r2.status_code, 200, 'другий webhook має відповісти 200')
        # Обидва записи створено — жодного «skipping» через порожній id.
        n = self.env['channel.message'].search_count(
            [('service', '=', 'viber'), ('direction', '=', 'incoming')]
        )
        self.assertEqual(n, 2, 'Б-6: два вхідні з порожнім id мають дати два записи')
