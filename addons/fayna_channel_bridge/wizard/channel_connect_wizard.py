# Copyright 2026 Fayna Digital — Volodymyr Shevchenko
# License OPL-1 (Odoo Proprietary License v1.0).
"""Wizard підключення token-каналів (Telegram, Viber) — Пакет 3, В-4.

Кнопка «Підключити» на token-каналі відкриває цей wizard з одним полем вводу
ключа (T-94: жодного ручного JSON і жодного URL вебхука). Після підтвердження
створюється/оновлюється `channel.backend`, ключ записується у відповідне поле,
а для Telegram одразу викликається реєстрація вебхука (FR-53, UX-18).

Помилки показуються людською мовою (UX-12) через декларативний словник причин,
щоб додавання нової причини не потребувало правки логіки.

🔴 OAuth у цьому пакеті НЕ реалізується. Для `connect_method = 'oauth'` wizard
не відкривається — підключення виконує адміністратор вручну.
"""

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _lt

# Декларативна мапа типових причин помилки → людське пояснення (UX-12).
# Ключ — підрядок, який шукаємо (регістронезалежно) у тексті помилки
# провайдера; значення — зрозуміле пояснення українською.
# Додавання нової причини = новий рядок у словнику, без правки логіки.
# Ж-4: константи рівня модуля використовують ліниву трансляцію `_lt`, бо
# звичайний `_()` обчислюється на імпорті, коли контексту користувача ще немає.
ERROR_REASON_MAP = [
    ("unauthorized", _lt("Invalid token. Check the key in the provider panel.")),
    ("forbidden", _lt("Access denied. Check the bot permissions at the provider.")),
    ("not found", _lt("A bot with this token was not found. Check the key.")),
    ("bad request", _lt("The provider rejected the request. Check the key format.")),
    ("timeout", _lt("Could not reach the provider server. Please try again.")),
    ("connection", _lt("Network problem. Check the connection and try again.")),
]

# Повідомлення-заглушка, якщо причина не збіглася з жодним відомим шаблоном.
_UNKNOWN_REASON = _lt(
    "Could not connect the channel. Contact the administrator for diagnostics."
)


class ChannelConnectWizard(models.TransientModel):
    """Wizard введення ключа для підключення token-каналу."""

    _name = "channel.connect.wizard"
    _description = "Token channel connection"

    provider_id = fields.Many2one(
        "channel.provider",
        string="Channel",
        required=True,
        ondelete="cascade",
    )
    token = fields.Char(
        string="Access key",
        required=True,
        help="Access key to the channel. The format is suggested by the placeholder.",
    )
    backend_id = fields.Many2one(
        "channel.backend",
        string="Connected backend",
        readonly=True,
    )

    def _humanize_error(self, raw_error):
        """Перетворює сирий текст помилки провайдера на людське пояснення.

        Шукає відомі причини в декларативному словнику `ERROR_REASON_MAP`
        (UX-12). Якщо причина невідома — повертає загальне пояснення, а не
        сирий код/текст провайдера.
        """
        if not raw_error:
            return _UNKNOWN_REASON
        lowered = str(raw_error).lower()
        for pattern, message in ERROR_REASON_MAP:
            if pattern in lowered:
                return message
        return _UNKNOWN_REASON

    def _find_or_create_backend(self):
        """Знаходить активний `channel.backend` для service або створює його."""
        self.ensure_one()
        service = self.provider_id.service
        backend = self.env["channel.backend"].search(
            [("service", "=", service), ("active", "=", True)], limit=1
        )
        if backend:
            return backend
        return self.env["channel.backend"].create(
            {
                "name": self.provider_id.name,
                "service": service,
                "provider": "direct",
                "transport_priority": "own",
            }
        )

    def _store_token(self, backend):
        """Записує ключ у відповідне поле backend залежно від каналу."""
        self.ensure_one()
        service = self.provider_id.service
        if service == "telegram":
            backend.write({"bot_token": self.token})
        elif service == "viber":
            creds = backend._get_credentials()
            creds["auth_token"] = self.token
            backend._set_credentials(creds)
        else:
            raise UserError(
                _("Channel %s does not support connecting via an access key.")
                % self.provider_id.name
            )

    def _register_webhook(self, backend):
        """Реєструє вебхук одразу після збереження ключа (FR-53).

        Для Telegram викликає наявний `register_telegram_webhook()`. Для Viber
        окремого методу реєстрації немає — лишаємо backend створеним і
        повідомляємо, що підписку треба зробити окремо (не вигадуємо).
        Повертає (ok, human_message).
        """
        self.ensure_one()
        service = self.provider_id.service
        if service == "telegram":
            ok, raw_error = backend.register_telegram_webhook()
            if ok:
                return True, _(
                    "Channel connected. The webhook was registered automatically."
                )
            return False, self._humanize_error(raw_error)
        if service == "viber":
            return True, _(
                "Channel connected. The Viber webhook subscription must be activated separately in the Viber panel."
            )
        return True, _("Channel connected.")

    def action_connect(self):
        """Головна дія wizard: зберегти ключ і підключити канал.

        Повертає словник результату (action) з людським повідомленням.
        Жоден секрет чи URL вебхука користувачеві не повертається (T-119).
        """
        self.ensure_one()
        if self.provider_id.connect_method != "token":
            raise UserError(
                _(
                    "Connecting %s is done manually by the administrator. "
                    "OAuth authorization is not implemented yet."
                )
                % self.provider_id.name
            )

        backend = self._find_or_create_backend()
        self._store_token(backend)
        self.backend_id = backend

        ok, message = self._register_webhook(backend)
        if not ok:
            raise UserError(message)

        return {
            "type": "ir.actions.act_window_close",
            "context": {"message": message},
        }
