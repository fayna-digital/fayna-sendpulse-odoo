# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Тести Пакету 5 — Д-3 (HC-02) та Д-4 (RET-02, EB-01, EB-03).

Покриває:
  - Д-3: `cron_bridge_healthcheck` для не-Telegram каналу пише нейтральний стан
    (last_healthcheck_ok=False + пояснення), а не брехливий `ok`;
  - Д-4: `cron_bridge_retry` розрізняє постійні й тимчасові помилки:
    постійна → `failed_permanent` без повторів; тимчасова → планує наступну
    спробу з експоненційною затримкою + jitter через `next_retry_at`;
  - Д-4: вибірка в кроні обмежена `limit` (F-17).
"""

from datetime import timedelta
from unittest.mock import Mock, patch

from odoo import fields
from odoo.addons.fayna_channel_bridge.models.channel_backend import ChannelBackend
from odoo.tests import TransactionCase, tagged


def _make_backend(env, service='viber', name='Test Viber'):
    """Створює активний backend власного транспорту."""
    return env['channel.backend'].create(
        {
            'name': name,
            'service': service,
            'provider': 'direct',
            'active': True,
        }
    )


def _make_failed_message(env, backend, retry_count=0, next_retry_at=None):
    """Створює вихідне повідомлення в стані `failed`."""
    return env['channel.message'].create(
        {
            'backend_id': backend.id,
            'service': backend.service,
            'direction': 'outgoing',
            'state': 'failed',
            'text_message': 'Привіт',
            'provider_user_id': '12345',
            'retry_count': retry_count,
            'next_retry_at': next_retry_at,
        }
    )


@tagged('post_install', '-at_install')
class TestPackage5Healthcheck(TransactionCase):
    """Д-3: HC-02 — нейтральний стан для не-Telegram каналів."""

    def test_d3_non_telegram_healthcheck_is_not_ok(self):
        """Д-3: для Viber після healthcheck `last_healthcheck_ok` не `True`."""
        backend = _make_backend(self.env, service='viber', name='Viber HC')
        self.env['channel.backend'].cron_bridge_healthcheck()
        backend.invalidate_recordset()
        self.assertFalse(
            backend.last_healthcheck_ok,
            'не-Telegram канал не має показувати зелений статус (HC-02)',
        )
        self.assertTrue(
            backend.last_error,
            'має бути пояснення нейтрального стану',
        )
        self.assertIn(
            'not implemented',
            backend.last_error,
            'пояснення має вказувати, що перевірка ще не реалізована',
        )

    def test_d3_telegram_healthcheck_still_works(self):
        """Д-3: Telegram-гілка healthcheck не зламана (мок setWebhook)."""
        backend = _make_backend(self.env, service='telegram', name='TG HC')
        backend.write({'bot_token': '123456:TESTTOKEN'})
        resp = Mock()
        resp.status_code = 200
        resp.text = '{"ok": true}'
        resp.json.return_value = {'ok': True}
        with patch('requests.post', return_value=resp):
            self.env['channel.backend'].cron_bridge_healthcheck()
        backend.invalidate_recordset()
        self.assertTrue(
            backend.last_healthcheck_ok,
            'Telegram-гілка має лишатись робочою',
        )


@tagged('post_install', '-at_install')
class TestPackage5Retry(TransactionCase):
    """Д-4: RET-02, EB-01, EB-03 — політика повторів."""

    def _run_retry(self, backend, result):
        """Запускає крон повторів, мокаючи `send_message` на заданий результат."""
        with patch.object(ChannelBackend, 'send_message', return_value=result):
            self.env['channel.backend'].cron_bridge_retry()

    def test_d4_permanent_error_marks_failed_permanent(self):
        """Д-4: постійна помилка → `failed_permanent`, повторів більше немає."""
        backend = _make_backend(self.env, service='viber', name='Viber Retry')
        msg = _make_failed_message(self.env, backend, retry_count=1)
        self._run_retry(backend, (False, None, 'Forbidden: bot was blocked by user'))
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'failed_permanent', 'постійна помилка → failed_permanent')
        self.assertFalse(msg.next_retry_at, 'для постійної помилки повтор не планується')
        self.assertIn('blocked', msg.last_error, 'має бути людське пояснення')

    def test_d4_temporary_error_plans_next_retry(self):
        """Д-4: тимчасова помилка → планується наступна спроба з backoff."""
        backend = _make_backend(self.env, service='viber', name='Viber Retry')
        msg = _make_failed_message(self.env, backend, retry_count=0)
        before = fields.Datetime.now()
        self._run_retry(backend, (False, None, 'Connection timeout'))
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'failed', 'тимчасова помилка лишається failed')
        self.assertEqual(msg.retry_count, 1, 'лічильник спроб зростає')
        self.assertTrue(msg.next_retry_at, 'має плануватись наступна спроба')
        # Затримка не менша за базу (15 хв) і не більша за кап (24 год).
        delay = msg.next_retry_at - before
        self.assertGreaterEqual(
            delay,
            timedelta(minutes=ChannelBackend._RETRY_BASE_MINUTES),
            'затримка не менша за базу',
        )
        self.assertLessEqual(
            delay,
            timedelta(minutes=ChannelBackend._RETRY_MAX_MINUTES + 5),
            'затримка не більша за кап + jitter',
        )

    def test_d4_backoff_grows_exponentially(self):
        """Д-4 (EB-01): затримка зростає з кількістю спроб."""
        t0 = ChannelBackend._compute_next_retry_at(0)
        t1 = ChannelBackend._compute_next_retry_at(1)
        t2 = ChannelBackend._compute_next_retry_at(2)
        # Кожна наступна спроба — пізніша (експоненційний ріст).
        self.assertGreater(t1, t0, 'спроба 1 пізніша за спробу 0')
        self.assertGreater(t2, t1, 'спроба 2 пізніша за спробу 1')

    def test_d4_success_clears_retry_state(self):
        """Д-4: успішна відправка → `sent`, повтор скинуто."""
        backend = _make_backend(self.env, service='viber', name='Viber Retry')
        msg = _make_failed_message(
            self.env, backend, retry_count=2, next_retry_at=fields.Datetime.now()
        )
        self._run_retry(backend, (True, 'msg_1', None))
        msg.invalidate_recordset()
        self.assertEqual(msg.state, 'sent', 'успіх → sent')
        self.assertFalse(msg.next_retry_at, 'next_retry_at очищено')
        self.assertFalse(msg.last_error, 'last_error очищено')

    def test_d4_search_has_limit(self):
        """Д-4 (F-17): вибірка в кроні обмежена `limit`."""
        # Перевіряємо, що константа ліміту задана й використовується.
        self.assertGreater(ChannelBackend._RETRY_BATCH_LIMIT, 0)
        # Створюємо більше повідомлень, ніж ліміт, і переконуємось,
        # що крон обробляє не більше ліміту за один прохід.
        backend = _make_backend(self.env, service='viber', name='Viber Retry')
        for _ in range(ChannelBackend._RETRY_BATCH_LIMIT + 5):
            _make_failed_message(self.env, backend, retry_count=0)
        self._run_retry(backend, (False, None, 'Connection timeout'))
        processed = self.env['channel.message'].search_count([('retry_count', '>', 0)])
        self.assertLessEqual(
            processed,
            ChannelBackend._RETRY_BATCH_LIMIT,
            'за один прохід крон обробляє не більше ліміту',
        )

    def test_d4_retry_batches_writes_fewer_queries_than_n(self):
        """Ж-6: крон із N невдалими повідомленнями робить менше запитів, ніж N.

        Усі N повідомлень падають з однаковою постійною помилкою → вони
        потрапляють в одну групу з однаковими значеннями, і `write`
        виконується одним батчем на recordset, а не на кожне повідомлення.
        """
        backend = _make_backend(self.env, service='viber', name='Viber Batch')
        n = 10
        for _ in range(n):
            _make_failed_message(self.env, backend, retry_count=0)
        self.env.flush_all()
        self.env.cr.flush()
        count0 = self.cr.sql_log_count
        with patch.object(
            ChannelBackend,
            'send_message',
            return_value=(False, None, 'Forbidden: bot was blocked by user'),
        ):
            self.env['channel.backend'].cron_bridge_retry()
        self.env.flush_all()
        self.env.cr.flush()
        count = self.cr.sql_log_count - count0
        self.assertLess(
            count,
            n,
            f'крон має робити менше запитів, ніж повідомлень ({count} >= {n})',
        )
