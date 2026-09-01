# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Модель-каталог `channel.provider` — декларативний довідник каналів.

Новий канал додається рядком даних, а не новим Python-кодом (FR-67, T-127).

Каталог ширший за наш транспорт: крім каналів, які ми підключаємо самі
(connect_method oauth/token), тут є:
- `native` — це вміє сам Odoo (Email → штатні поштові сервери; LiveChat →
  im_livechat; SMS → fayna_sms_base / fayna_sms_turbosms). Ведемо в його
  налаштування, не дублюємо.
- `external` — маркетплейс-інтеграції (Telegram особистий, Viber особистий,
  LinkedIn Chatbots). Картка веде посиланням назовні, кнопка — «Перейти».

Зв'язок із `channel.backend` — лише для наших каналів (oauth/token).
Для native/external статусу підключення немає взагалі — там інша дія.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Власний Selection каталогу — надмножина `channel.backend.SERVICE_SELECTION`.
# `channel.backend` не чіпаємо (ТЗ §1): тут додаємо значення, яких там немає
# (email, sms, linkedin, telegram_personal, viber_personal), бо вони не мають
# власного транспорту — це native/external картки.
PROVIDER_CATALOG_SELECTION = [
    ('telegram', 'Telegram'),
    ('instagram', 'Instagram'),
    ('facebook', 'Facebook'),
    ('messenger', 'Messenger'),
    ('viber', 'Viber'),
    ('whatsapp', 'WhatsApp'),
    ('tiktok', 'TikTok'),
    ('livechat', 'LiveChat'),
    ('email', 'Email'),
    ('sms', 'SMS'),
    ('linkedin', 'LinkedIn'),
    ('telegram_personal', 'Telegram personal'),
    ('viber_personal', 'Viber personal'),
]

CONNECT_METHOD_SELECTION = [
    ('oauth', 'OAuth'),
    ('token', 'Token'),
    ('widget', 'Widget'),
    ('settings', 'Settings'),
    ('native', 'Native (Odoo)'),
    ('external', 'External (marketplace)'),
]

# Категорії лівої панелі OWL-SPA (порядок категорій захардкоджений у JS,
# склад — дані). Поле називається `category` (main / marketplace).
PROVIDER_CATEGORY_SELECTION = [
    ('main', 'Main'),
    ('marketplace', 'Marketplace integrations'),
]

# Три чесні стани каналу (ТЗ §0.1): не налаштовано / потребує уваги / працює.
# Джерело правди — last_healthcheck_ok + last_error у channel.backend.
# Для native/external стану підключення немає — там інша дія.
PROVIDER_STATE_SELECTION = [
    ('not_configured', 'Not configured'),
    ('needs_attention', 'Needs attention'),
    ('working', 'Working'),
]

# Методи, для яких шукаємо `channel.backend` (наші канали).
_BACKEND_METHODS = ('oauth', 'token')


class ChannelProvider(models.Model):
    """Довідник каналів для SPA «Підключити канали»."""

    _name = 'channel.provider'
    _description = 'Channel Provider (channel catalog)'
    _order = 'sequence asc, name asc'

    name = fields.Char(string='Name', required=True, translate=True)
    service = fields.Selection(
        PROVIDER_CATALOG_SELECTION,
        string='Channel',
        required=True,
        index=True,
    )
    sequence = fields.Integer(string='Order', default=10)
    category = fields.Selection(
        PROVIDER_CATEGORY_SELECTION,
        string='Panel category',
        default='main',
        required=True,
    )
    connect_method = fields.Selection(
        CONNECT_METHOD_SELECTION,
        string='Connection method',
        required=True,
    )
    token_placeholder = fields.Char(string='Key format example', translate=True)
    help_url = fields.Char(string='How to get an access key?', translate=True)
    description = fields.Text(string='Description', translate=True)
    precondition_ids = fields.Text(
        string='Preconditions',
        translate=True,
        help='Preconditions to complete BEFORE connecting (one per line).',
    )
    region_blocklist = fields.Char(string='Unavailable regions', translate=True)
    consent_required = fields.Boolean(string='Consent required')
    cost_warning = fields.Char(string='Cost warning', translate=True)
    side_effect_warning = fields.Char(string='Side effect warning', translate=True)
    active = fields.Boolean(string='Active', default=True)

    # ── Рядки правої панелі SPA (ТЗ §2.2) ───────────────────────────────
    value_line = fields.Char(
        string='Value line',
        translate=True,
        help='One line: "what I get" (benefit of connecting this channel).',
    )
    permission_line = fields.Char(
        string='Permission line',
        translate=True,
        help='One line: "what I give" (permissions the channel requires).',
    )
    connect_label = fields.Char(
        string='Connect button label',
        translate=True,
        help='Label of the single primary button (defaults to "Connect").',
    )
    fallback_label = fields.Char(
        string='Fallback link label',
        translate=True,
        help='Label of the fallback link (defaults to "Learn more").',
    )
    fallback_url = fields.Char(
        string='Fallback link URL',
        help='URL of the fallback link (help / manual setup instructions).',
    )

    # ── Обчислювані (не зберігаються) ──────────────────────────────────
    backend_id = fields.Many2one(
        'channel.backend',
        string='Connected backend',
        compute='_compute_connection',
    )
    is_connected = fields.Boolean(
        string='Connected',
        compute='_compute_connection',
    )
    has_credentials = fields.Boolean(
        string='Has credentials',
        compute='_compute_connection',
    )
    state = fields.Selection(
        PROVIDER_STATE_SELECTION,
        string='State',
        compute='_compute_connection',
    )
    state_label = fields.Char(
        string='State label',
        compute='_compute_connection',
    )
    status_label = fields.Char(
        string='Status',
        compute='_compute_connection',
    )

    # ── Підтвердження передумов (UX-15/UX-16, Е-2) ─────────────────────
    # Регіон і згоду автовизначити неможливо (заборонено геолокацію/IP/мову),
    # тому гейт — явне підтвердження людиною у формі каналу.
    region_confirmed = fields.Boolean(
        string='Confirmed: working outside the restricted regions',
        help='Check this if the channel is used outside the listed regions.',
    )
    consent_confirmed = fields.Boolean(
        string='User consent obtained',
        help='Check this once the user consent to connect the channel is obtained.',
    )
    has_unconfirmed_preconditions = fields.Boolean(
        string='Has unconfirmed preconditions',
        compute='_compute_precondition_gate',
    )
    blocking_reason = fields.Char(
        string='Blocking reason',
        compute='_compute_precondition_gate',
    )

    @api.depends(
        'region_blocklist',
        'region_confirmed',
        'consent_required',
        'consent_confirmed',
    )
    def _compute_precondition_gate(self):
        """Рахує непідтверджені передумови і людську причину (UX-16)."""
        for provider in self:
            reasons = []
            if provider.region_blocklist and not provider.region_confirmed:
                reasons.append(
                    _('Confirm that the channel works outside the restricted regions: %s')
                    % provider.region_blocklist
                )
            if provider.consent_required and not provider.consent_confirmed:
                reasons.append(_('Confirm the user consent to connect the channel.'))
            provider.has_unconfirmed_preconditions = bool(reasons)
            provider.blocking_reason = ' '.join(reasons)

    @api.depends('service', 'connect_method')
    def _compute_connection(self):
        """Знаходить активний `channel.backend` і рахує чесний стан (§0.1).

        Зв'язок із бекендом — лише для наших каналів (connect_method у
        ('oauth', 'token')). Для native/external статусу підключення немає
        взагалі — там інша дія (налаштування Odoo / зовнішнє посилання).

        Три стани замість двох:
        - not_configured — бекенда немає, або немає ні токена, ні credentials;
        - needs_attention — облікові дані є, але остання перевірка провалилась
          (протух токен, відкликано доступ) або healthcheck не підтримується;
        - working — остання перевірка успішна.

        Джерело правди — last_healthcheck_ok + last_error у channel.backend.
        Для Meta-каналів healthcheck не реалізований, тому чесний стан —
        needs_attention (перевірка не підтримується), а НЕ working.
        """
        backend_methods = [p.service for p in self if p.connect_method in _BACKEND_METHODS]
        backends = self.env['channel.backend'].search(
            [('service', 'in', backend_methods), ('active', '=', True)]
        )
        backend_by_service = {b.service: b for b in backends}
        for provider in self:
            if provider.connect_method not in _BACKEND_METHODS:
                # native/external — немає власного бекенда і статусу підключення.
                provider.backend_id = False
                provider.is_connected = False
                provider.has_credentials = False
                provider.state = False
                provider.state_label = False
                provider.status_label = False
                continue
            backend = backend_by_service.get(provider.service)
            provider.backend_id = backend.id if backend else False
            provider.is_connected = bool(backend)
            provider.has_credentials = bool(backend and (backend.bot_token or backend.credentials))
            provider.state, provider.state_label, provider.status_label = self._resolve_state(
                backend
            )

    def _resolve_state(self, backend):
        """Повертає (state, state_label, status_label) для одного каналу."""
        not_configured = _('Not configured')
        needs_attention = _('Needs attention')
        working = _('Working')
        if not backend:
            return 'not_configured', not_configured, not_configured
        if not (backend.bot_token or backend.credentials):
            # Запис є, але облікових даних немає — фактично не налаштовано.
            return 'not_configured', not_configured, not_configured
        if backend.last_healthcheck_ok:
            return 'working', working, working
        # Облікові дані є, але перевірка не пройшла або не підтримується.
        return 'needs_attention', needs_attention, needs_attention

    def action_connect(self):
        """Головна дія «Підключити» на екрані каналу.

        Для token-каналів (Telegram, Viber) відкриває wizard введення ключа.
        Для OAuth-каналів (Messenger, Instagram, WhatsApp, TikTok) повертає
        URL авторизації (реалізується у Фазі 2). Для widget/settings —
        інструкцію або налаштування. Для native/external — ця дія не
        викликається (там «Перейти» / налаштування Odoo).

        🔴 Серверний гейт (Е-2): якщо передумови не підтверджені — відмова
        з людською причиною. Схована кнопка — не захист: дію можна викликати
        в обхід UI.
        """
        self.ensure_one()
        if self.connect_method in ('native', 'external'):
            raise UserError(_('Channel %s is not connected through this screen.') % self.name)
        if self.has_unconfirmed_preconditions:
            raise UserError(self.blocking_reason)
        if self.connect_method == 'token':
            return {
                'name': _('Connect %s') % self.name,
                'type': 'ir.actions.act_window',
                'res_model': 'channel.connect.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_provider_id': self.id},
            }
        if self.connect_method == 'oauth':
            # Фаза 2: повертає URL авторизації Meta. Поки що — чесна відмова.
            raise UserError(
                _(
                    'Connecting %s requires OAuth authorization, which is not '
                    'configured yet. Please set up the Meta app first.'
                )
                % self.name
            )
        if self.connect_method == 'settings':
            raise UserError(_('Channel %s is configured in the Odoo settings.') % self.name)
        # widget-канали — авторизація не потрібна
        raise UserError(
            _('Channel %s does not require connecting — just embed the widget.') % self.name
        )

    def action_open_backend(self):
        """Дія «Відкрити канал» на картці вже підключеного каналу.

        Відкриває форму підключеного `channel.backend` (Д-1.1). Якщо backend
        не знайдено — повертає на форму провайдера.
        """
        self.ensure_one()
        if self.backend_id:
            return {
                'name': _('Channel %s') % self.name,
                'type': 'ir.actions.act_window',
                'res_model': 'channel.backend',
                'view_mode': 'form',
                'res_id': self.backend_id.id,
            }
        return self.action_connect()

    def action_disconnect(self):
        """UX-аудит (Ш6/Т8): дія «Відключити» на картці підключеного каналу.

        Архівує підключений `channel.backend` (active=False). Канал зникає з
        галереї як «Connected» і повертається до стану «Not connected».
        Архівація (а не видалення) зберігає історію повідомлень і журнал.
        """
        self.ensure_one()
        if not self.backend_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Not connected'),
                    'message': _('This channel is not connected.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        backend = self.backend_id
        backend.write({'active': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Channel disconnected'),
                'message': _('%s has been disconnected.') % self.name,
                'type': 'success',
                'sticky': False,
            },
        }

    # ── RPC для OWL-SPA (ТЗ §2.3) ───────────────────────────────────────
    def get_dashboard_data(self):
        """Повертає всі активні канали для лівої панелі і правої панелі SPA.

        Один RPC на відкриття екрана. Ліва панель і вміст правої беруться з
        `channel.provider` — новий канал = рядок даних, не правка JS.
        Порядок категорій задається в JS, склад категорій — тут (поле
        `category`).
        """
        providers = self.search([('active', '=', True)])
        return [
            {
                'id': p.id,
                'name': p.name,
                'service': p.service,
                'category': p.category,
                'connect_method': p.connect_method,
                'state': p.state,
                'state_label': p.state_label,
                'is_connected': p.is_connected,
                'has_credentials': p.has_credentials,
                'value_line': p.value_line,
                'permission_line': p.permission_line,
                'description': p.description,
                'connect_label': p.connect_label or _('Connect'),
                'fallback_label': p.fallback_label or _('Learn more'),
                'fallback_url': p.fallback_url,
                'help_url': p.help_url,
                'token_placeholder': p.token_placeholder,
                'precondition_ids': p.precondition_ids,
                'region_blocklist': p.region_blocklist,
                'consent_required': p.consent_required,
                'cost_warning': p.cost_warning,
                'side_effect_warning': p.side_effect_warning,
                'has_unconfirmed_preconditions': p.has_unconfirmed_preconditions,
                'blocking_reason': p.blocking_reason,
            }
            for p in providers
        ]

    def get_oauth_url(self):
        """Повертає URL авторизації OAuth для каналу (ТЗ §2.4, Фаза 2).

        Викликається з OWL-SPA для `connect_method == 'oauth'`. У Фазі 2
        повертає реальний URL авторизації Meta. Поки що — чесна відмова,
        щоб UI не показував хибний успіх.
        """
        self.ensure_one()
        if self.connect_method != 'oauth':
            raise UserError(_('Channel %s does not use OAuth authorization.') % self.name)
        # Фаза 2: тут буде побудова URL авторизації Meta (scopes, redirect URI).
        raise UserError(
            _(
                'Connecting %s requires OAuth authorization, which is not '
                'configured yet. Please set up the Meta app first.'
            )
            % self.name
        )
