# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Модель-каталог `channel.provider` — декларативний довідник каналів.

Новий канал додається рядком даних, а не новим Python-кодом (FR-67, T-127).
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .channel_backend import SERVICE_SELECTION

CONNECT_METHOD_SELECTION = [
    ("oauth", "OAuth"),
    ("token", "Token"),
    ("widget", "Widget"),
]


class ChannelProvider(models.Model):
    """Довідник каналів для галереї «Підключити канали»."""

    _name = "channel.provider"
    _description = "Channel Provider (channel catalog)"
    _order = "sequence asc, name asc"

    name = fields.Char(string="Name", required=True, translate=False)
    service = fields.Selection(
        SERVICE_SELECTION,
        string="Channel",
        required=True,
        index=True,
    )
    sequence = fields.Integer(string="Order", default=10)
    connect_method = fields.Selection(
        CONNECT_METHOD_SELECTION,
        string="Connection method",
        required=True,
    )
    token_placeholder = fields.Char(string="Key format example")
    help_url = fields.Char(string="How to get an access key?")
    description = fields.Text(string="Description")
    precondition_ids = fields.Text(
        string="Preconditions",
        help="Preconditions to complete BEFORE connecting (one per line).",
    )
    region_blocklist = fields.Char(string="Unavailable regions")
    consent_required = fields.Boolean(string="Consent required")
    cost_warning = fields.Char(string="Cost warning")
    side_effect_warning = fields.Char(string="Side effect warning")
    active = fields.Boolean(string="Active", default=True)

    # ── Обчислювані (не зберігаються) ──────────────────────────────────
    backend_id = fields.Many2one(
        "channel.backend",
        string="Connected backend",
        compute="_compute_connection",
    )
    is_connected = fields.Boolean(
        string="Connected",
        compute="_compute_connection",
    )
    status_label = fields.Char(
        string="Status",
        compute="_compute_connection",
    )

    # ── Підтвердження передумов (UX-15/UX-16, Е-2) ─────────────────────
    # Регіон і згоду автовизначити неможливо (заборонено геолокацію/IP/мову),
    # тому гейт — явне підтвердження людиною у формі каналу.
    region_confirmed = fields.Boolean(
        string="Confirmed: working outside the restricted regions",
        help="Check this if the channel is used outside the listed regions.",
    )
    consent_confirmed = fields.Boolean(
        string="User consent obtained",
        help="Check this once the user consent to connect the channel is obtained.",
    )
    has_unconfirmed_preconditions = fields.Boolean(
        string="Has unconfirmed preconditions",
        compute="_compute_precondition_gate",
    )
    blocking_reason = fields.Char(
        string="Blocking reason",
        compute="_compute_precondition_gate",
    )

    @api.depends(
        "region_blocklist",
        "region_confirmed",
        "consent_required",
        "consent_confirmed",
    )
    def _compute_precondition_gate(self):
        """Рахує непідтверджені передумови і людську причину (UX-16)."""
        for provider in self:
            reasons = []
            if provider.region_blocklist and not provider.region_confirmed:
                reasons.append(
                    _(
                        "Confirm that the channel works outside the restricted regions: %s"
                    )
                    % provider.region_blocklist
                )
            if provider.consent_required and not provider.consent_confirmed:
                reasons.append(_("Confirm the user consent to connect the channel."))
            provider.has_unconfirmed_preconditions = bool(reasons)
            provider.blocking_reason = " ".join(reasons)

    @api.depends("service")
    def _compute_connection(self):
        """Знаходить активний `channel.backend` із таким самим `service`."""
        backends = self.env["channel.backend"].search(
            [("service", "in", self.mapped("service")), ("active", "=", True)]
        )
        backend_by_service = {b.service: b for b in backends}
        for provider in self:
            backend = backend_by_service.get(provider.service)
            provider.backend_id = backend.id if backend else False
            provider.is_connected = bool(backend)
            provider.status_label = "Connected" if backend else "Not connected"

    def action_connect(self):
        """Головна дія «Підключити» на формі провайдера.

        Для token-каналів (Telegram, Viber) відкриває wizard введення ключа
        (реалізовано у В-4). Для OAuth-каналів підключення виконується
        адміністратором вручну — OAuth у цьому пакеті не реалізується.

        🔴 Серверний гейт (Е-2): якщо передумови не підтверджені — відмова
        з людською причиною. Схована кнопка — не захист: дію можна викликати
        в обхід UI.
        """
        self.ensure_one()
        if self.has_unconfirmed_preconditions:
            raise UserError(self.blocking_reason)
        if self.connect_method == "token":
            return {
                "name": _("Connect %s") % self.name,
                "type": "ir.actions.act_window",
                "res_model": "channel.connect.wizard",
                "view_mode": "form",
                "target": "new",
                "context": {"default_provider_id": self.id},
            }
        if self.connect_method == "oauth":
            raise UserError(
                _(
                    "Connecting %s is done manually by the administrator. "
                    "OAuth authorization is not implemented yet."
                )
                % self.name
            )
        # widget-канали (LiveChat) — авторизація не потрібна
        raise UserError(
            _("Channel %s does not require connecting — just embed the widget.")
            % self.name
        )

    def action_open_backend(self):
        """Дія «Відкрити канал» на картці вже підключеного каналу.

        Відкриває форму підключеного `channel.backend` (Д-1.1). Якщо backend
        не знайдено — повертає на форму провайдера.
        """
        self.ensure_one()
        if self.backend_id:
            return {
                "name": _("Channel %s") % self.name,
                "type": "ir.actions.act_window",
                "res_model": "channel.backend",
                "view_mode": "form",
                "res_id": self.backend_id.id,
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
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Not connected"),
                    "message": _("This channel is not connected."),
                    "type": "warning",
                    "sticky": False,
                },
            }
        backend = self.backend_id
        backend.write({"active": False})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Channel disconnected"),
                "message": _("%s has been disconnected.") % self.name,
                "type": "success",
                "sticky": False,
            },
        }
