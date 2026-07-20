# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Фаза 1 — characterization-тести `SendpulseConnect._process_incoming_event`.

Пріоритет №1 з ТЗ рефакторингу: найризикованіший, найбільш використовуваний
шлях коду (webhook entry point для КОЖНОГО вхідного повідомлення з усіх
каналів). Мета — не «має бути правильно», а «так і робить зараз», щоб
Фаза 3 (розбиття God Object) мала виконуваний контракт для звірки.

Покриває:
  - race-guard (advisory lock) + fallback-відновлення після IntegrityError
    на partial unique index (сама конкурентність двома реальними
    транзакціями тут НЕ відтворюється — TransactionCase однопотоковий;
    замість цього тест напряму б'є по catch-гілці, підміняючи перший
    create() на IntegrityError, як і реально стається при перегонах)
  - regression-тест на інцидент втрати повідомлень 2026-07-19: raw SQL
    UPDATE у _update_partner_source() без savepoint раніше зносив ВЕСЬ
    request-transaction, включно з щойно створеним sendpulse.message
  - основний happy-path (нова розмова, оновлення існуючої)
"""
from unittest.mock import patch

from psycopg2 import IntegrityError

from .common import SendpulseWebhookTestCase


class TestProcessIncomingEvent(SendpulseWebhookTestCase):
    def test_creates_new_connect_with_unidentified_contact(self):
        """Новий контакт без збігу ІСНУЮЧОГО партнера (_find_partner
        повертає None) → sendpulse.connect у "неідентифікованому" стані
        (unidentified_email заповнено).

        ⚠️ Характеризує НЕОЧЕВИДНУ поведінку (перевірено живим прогоном,
        не з коду на око): "неідентифікований" НЕ означає connect.partner_id
        залишається порожнім! Код нижче за течією ("Ensure incoming
        Discuss messages always have a customer author") САМ створює
        новий res.partner (щоб було кому бути автором повідомлення в
        Discuss) і одразу лінкує його як connect.partner_id — окремий,
        незалежний від _find_partner механізм. Тобто в одному записі
        одночасно можуть бути І unidentified_email=... І partner_id=...
        (просто partner_id вказує на ЩОЙНО створеного партнера, не на
        знайденого існуючого). Вартий уваги для Фази 3 — легко
        припустити протилежне."""
        Connect = self.env['sendpulse.connect']
        contact = self._contact(
            id='new-1', name='Іван Новий', email='ivan.new@example.com', last_message='Привіт!'
        )
        connect = Connect._process_incoming_event(
            {}, contact, self._bot(), 'telegram', 'incoming_message', 0
        )
        self.assertTrue(connect)
        self.assertEqual(connect.sendpulse_contact_id, 'new-1')
        self.assertEqual(connect.service, 'telegram')
        self.assertEqual(connect.unidentified_email, 'ivan.new@example.com')
        self.assertTrue(
            connect.partner_id,
            'partner_id ВСЕ ОДНО заповнюється — автостворений author-партнер, не знайдений',
        )
        self.assertEqual(connect.partner_id.email, 'ivan.new@example.com')
        msg = self.env['sendpulse.message'].search([('connect_id', '=', connect.id)])
        self.assertEqual(len(msg), 1)
        self.assertEqual(msg.text_message, 'Привіт!')
        self.assertEqual(msg.direction, 'incoming')

    def test_second_call_same_contact_updates_not_duplicates(self):
        """Два вебхуки для того самого (contact_id, service) — типова
        ситуація коли клієнт пише кілька повідомлень поспіль — НЕ повинні
        створювати два sendpulse.connect. Це функціональний контракт, який
        захищає advisory lock (pg_advisory_xact_lock) + partial unique
        index у полі."""
        Connect = self.env['sendpulse.connect']
        contact1 = self._contact(id='rep-1', last_message='Перше')
        c1 = Connect._process_incoming_event(
            {}, contact1, self._bot(), 'telegram', 'incoming_message', 0
        )
        contact2 = self._contact(id='rep-1', last_message='Друге')
        c2 = Connect._process_incoming_event(
            {}, contact2, self._bot(), 'telegram', 'incoming_message', 0
        )
        self.assertEqual(c1, c2, 'другий виклик оновлює той самий запис, не створює новий')
        self.assertEqual(
            Connect.search_count([('sendpulse_contact_id', '=', 'rep-1')]),
            1,
            'жодного дубля sendpulse.connect',
        )
        msgs = self.env['sendpulse.message'].search(
            [('connect_id', '=', c1.id)], order='date'
        )
        self.assertEqual(len(msgs), 2, 'обидва повідомлення збережені')
        self.assertEqual(msgs.mapped('text_message'), ['Перше', 'Друге'])

    def test_integrity_error_on_create_recovers_existing_record(self):
        """Симулює те, що в реальності ловить partial unique index при
        двох майже одночасних webhook-ах: наш `self.create()` кидає
        IntegrityError, бо ІНШИЙ worker вже закомітив свій запис для
        того самого (contact_id, service). Код (`except IntegrityError:`
        у `_process_incoming_event`) повинен відкотити наш невдалий
        create() через savepoint і підхопити запис іншого worker-а
        замість падіння чи дубля.

        ПРИМІТКА щодо дизайну тесту (важливо для майбутніх сесій — двічі
        наступав на ці граблі, поки писав цей тест, обидва рази
        перевірено живим прогоном, не здогадкою):

        1. «Інший worker» НЕ можна змоделювати окремим
           `self.registry.cursor()` з реальним commit(): Odoo-курсори за
           замовчуванням `ISOLATION_LEVEL_REPEATABLE_READ` (snapshot
           isolation, `odoo/sql_db.py`), а знімок транзакції тесту
           зафіксований задовго до цього методу — навіть реально
           закомічений запис з іншого зʼєднання лишається невидимим для
           `search()` у транзакції тесту НАЗАВЖДИ (не «поки не
           закомітиться», а структурно, для всієї тривалості тесту).
        2. Просте write() у ТІЙ САМІЙ транзакції теж не рятує: увесь
           `self.create(create_vals)` (=наш flaky_create) виконується
           ВСЕРЕДИНІ `with self.env.cr.savepoint():` коду під тестом.
           Будь-який запис, зроблений усередині flaky_create, живе лише
           до моменту коли savepoint робить `ROLLBACK TO SAVEPOINT` на
           виході з блоку через виняток — і зникає РАЗОМ із невдалим
           create(), ще до того як `except IntegrityError:` встигає
           щось прочитати.

        Тому тут напряму мокається САМЕ recovery-search (пошук, що йде
        ПІСЛЯ IntegrityError, за тим самим доменом що й initial-search) —
        це тестує КОНТРОЛЬ-ФЛОУ відновлення (catch → invalidate → search
        → use found record, без падіння й без дубля), а не намагається
        відтворити справжню між-транзакційну гонку (що в TransactionCase
        структурно неможливо через п.1-2 вище).
        """
        Connect = self.env['sendpulse.connect']
        contact = self._contact(id='race-1', last_message='Повідомлення під час гонки')

        other_worker_record = Connect.create(
            {
                'name': 'Вже створено іншим воркером',
                'service': 'telegram',
                'sendpulse_contact_id': 'race-1-other-worker-placeholder',
                'stage': 'new',
            }
        )
        recovery_domain = [
            ('sendpulse_contact_id', '=', 'race-1'),
            ('service', '=', 'telegram'),
            ('stage', '!=', 'close'),
        ]

        model_cls = type(Connect)
        real_create = model_cls.create
        real_search = model_cls.search
        state = {'create_raised': False}

        def flaky_create(rec_self, vals_list, *a, **kw):
            if not state['create_raised']:
                state['create_raised'] = True
                raise IntegrityError(
                    'duplicate key value violates unique constraint '
                    '"sendpulse_connect_contact_service_active_uniq"'
                )
            return real_create(rec_self, vals_list, *a, **kw)

        def search_with_other_worker_after_raise(rec_self, args, *a, **kw):
            # Лише ПІСЛЯ того як create() впав — підміняємо результат
            # РІВНО для recovery-домену (та сама умова, що й
            # initial-search перед create(), тому їх не можна розрізнити
            # інакше ніж по прапорцю "вже впало"). Усі інші search()
            # виклики (advisory-lock гілки, priority-2/3 пошуки тощо)
            # йдуть через реальний search() без змін.
            if state['create_raised'] and args == recovery_domain:
                return other_worker_record
            return real_search(rec_self, args, *a, **kw)

        with patch.object(model_cls, 'create', flaky_create), patch.object(
            model_cls, 'search', search_with_other_worker_after_raise
        ):
            result = Connect._process_incoming_event(
                {}, contact, self._bot(), 'telegram', 'incoming_message', 0
            )

        self.assertTrue(
            state['create_raised'], 'тест не має сенсу якщо create() не було перехоплено'
        )
        self.assertEqual(
            result,
            other_worker_record,
            'після IntegrityError код підхоплює запис іншого worker-а, не падає',
        )

    def test_survives_partner_source_update_failure(self):
        """РЕГРЕСІЙНИЙ тест на інцидент 2026-07-19 (docs/INCIDENT_MESSAGE_LOSS_2026-07-19.md).

        Корінь інциденту: _update_partner_source() робив raw SQL
        `UPDATE partner_sendpulse_channel SET message_count = message_count + 1`
        БЕЗ savepoint. Serialization-конфлікт на цьому UPDATE (два вебхуки
        по тому самому клієнту майже одночасно) абортував ВСЮ транзакцію
        запиту — разом із щойно створеним sendpulse.message. SendPulse
        бачив HTTP 200 і ніколи не ретраїв → повідомлення клієнта зникало
        безслідно.

        Фікс (v17.0.15.3, коміт d6f89a3) — `with self.env.cr.savepoint():`
        навколо САМЕ цього UPDATE. Тест відтворює РЕАЛЬНИЙ Postgres-збій
        (не мокає exception на Python-рівні — інакше сама транзакція
        Postgres не встигає «отруїтись» і тест нічого не перевіряє):
        підміняє SQL на завідомо невалидну колонку, щоб psycopg2 кинув
        справжню помилку всередині savepoint-блоку. Якщо savepoint колись
        приберуть — цей тест впаде або через виняток що випливає з
        _process_incoming_event, або через те що повідомлення не
        переживає збій.
        """
        Connect = self.env['sendpulse.connect']
        partner = self.env['res.partner'].create(
            {'name': 'Ганна Клієнтка', 'email': 'ganna.race@example.com'}
        )

        contact1 = self._contact(id='sp-race-1', email='ganna.race@example.com', last_message='Перше')
        c1 = Connect._process_incoming_event(
            {}, contact1, self._bot(), 'telegram', 'incoming_message', 0
        )
        self.assertEqual(c1.partner_id, partner)
        channel_rec = self.env['partner.sendpulse.channel'].search(
            [('partner_id', '=', partner.id), ('service', '=', 'telegram')]
        )
        self.assertTrue(
            channel_rec, 'перший inbound створює partner.sendpulse.channel (гілка без UPDATE)'
        )

        # Другий виклик потрапляє у гілку `existing` → саме той raw UPDATE,
        # який захищений savepoint-ом. Псуємо ЛИШЕ цей один запит —
        # решта SQL (ORM create/write) йде через реальний execute як є.
        real_execute = self.env.cr.execute

        def flaky_execute(query, params=None, *a, **kw):
            if isinstance(query, str) and 'UPDATE partner_sendpulse_channel SET message_count' in query:
                query = query.replace('message_count = message_count + 1', 'no_such_column_xyz = 1')
            return real_execute(query, params, *a, **kw)

        contact2 = self._contact(
            id='sp-race-1',
            email='ganna.race@example.com',
            last_message='Друге (під час симульованого serialization-збою)',
        )
        with patch.object(self.env.cr, 'execute', side_effect=flaky_execute):
            c2 = Connect._process_incoming_event(
                {}, contact2, self._bot(), 'telegram', 'incoming_message', 0
            )

        # 1) виклик не впав — savepoint зловив psycopg2-помилку, метод
        #    _update_partner_source() лише залогував warning.
        self.assertTrue(c2)

        # 2) ГОЛОВНЕ: sendpulse.message другого inbound ПЕРЕЖИВ збій
        #    UPDATE, що стався ПІЗНІШЕ у тій самій обробці. Це саме те,
        #    що губилось до фіксу.
        msg = self.env['sendpulse.message'].search(
            [
                ('connect_id', '=', c2.id),
                ('text_message', '=', 'Друге (під час симульованого serialization-збою)'),
            ]
        )
        self.assertTrue(
            msg, 'inbound-повідомлення має пережити збій UPDATE у _update_partner_source (savepoint)'
        )

        # 3) транзакція не «отруєна» — подальші ORM-операції в тому ж cr
        #    досі працюють (без savepoint тут би вилетів
        #    InFailedSqlTransaction на БУДЬ-ЯКИЙ наступний запит).
        partner.write({'name': 'Ганна Клієнтка (перевірено після збою)'})
        self.assertEqual(partner.name, 'Ганна Клієнтка (перевірено після збою)')

    def test_existing_conversation_reopens_on_new_message_after_close(self):
        """Пріоритет 3 у _process_incoming_event: закрита розмова того ж
        контакту перевідкривається (stage → new) замість створення нової."""
        Connect = self.env['sendpulse.connect']
        contact = self._contact(id='reopen-1', last_message='Перше')
        c1 = Connect._process_incoming_event(
            {}, contact, self._bot(), 'telegram', 'incoming_message', 0
        )
        c1.write({'stage': 'close'})

        contact2 = self._contact(id='reopen-1', last_message='Повернувся')
        c2 = Connect._process_incoming_event(
            {}, contact2, self._bot(), 'telegram', 'incoming_message', 0
        )
        self.assertEqual(c1, c2, 'перевідкриває той самий запис, не створює нового')
        self.assertEqual(c2.stage, 'new')
        self.assertEqual(
            Connect.search_count([('sendpulse_contact_id', '=', 'reopen-1')]),
            1,
        )
