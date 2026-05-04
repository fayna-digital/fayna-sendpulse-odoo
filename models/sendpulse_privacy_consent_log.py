import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SendpulsePrivacyConsentLog(models.Model):
    """
    Append-only журнал згод RODO/GDPR для lead-magnet flow.

    PL PKE (Prawo komunikacji elektronicznej) вимагає окремих consent-ів
    per-channel (email і SMS — це різні комунікаційні канали). Цей модель
    фіксує КОЖНУ подію надання або відкликання згоди — хто, коли, на що,
    буквально ЯКИМИ СЛОВАМИ клієнт її надав, звідки прийшла (чат/форма/
    ручно), з посиланням на доказ (sendpulse.message).

    Append-only: perm_unlink=0 для всіх. Адмін може тільки "виправити"
    через створення нового запису з withdrawal.
    """

    _name = 'sendpulse.privacy.consent.log'
    _description = 'Privacy Consent Log (RODO/GDPR/PKE)'
    _order = 'consent_timestamp desc, id desc'
    _rec_name = 'display_name'

    partner_id = fields.Many2one(
        'res.partner',
        string='Партнер',
        ondelete='set null',
        index=True,
    )
    connect_id = fields.Many2one(
        'sendpulse.connect',
        string='Розмова',
        ondelete='set null',
        index=True,
    )
    message_id = fields.Many2one(
        'sendpulse.message',
        string='Доказ (повідомлення)',
        ondelete='set null',
        help='Повідомлення клієнта у чаті, яке містило згоду або contact-'
        'дані. Юридичний доказ на випадок суперечки з RODO-регулятором.',
    )

    email = fields.Char(string='Email', index=True)
    phone = fields.Char(string='Телефон', index=True)

    purpose = fields.Selection(
        [
            ('lead_magnet_email', 'Lead magnet: PDF-каталог на email'),
            ('lead_magnet_sms', 'Lead magnet: SMS-купон'),
            ('marketing_email', 'Marketing email (розсилки)'),
            ('marketing_sms', 'Marketing SMS'),
            ('transactional', 'Транзакційні (бронювання, оплата)'),
            ('other', 'Інше'),
        ],
        string='Мета обробки',
        required=True,
        index=True,
    )

    channel = fields.Selection(
        [
            ('email', 'Email'),
            ('sms', 'SMS'),
            ('phone', 'Телефон (дзвінок)'),
            ('messenger', 'Messenger (Telegram/WA/IG/FB)'),
            ('website', 'Website form'),
        ],
        string='Канал',
        required=True,
        index=True,
    )

    legal_basis = fields.Selection(
        [
            ('consent', 'Згода (art. 6(1)(a) RODO)'),
            ('contract', 'Виконання договору (art. 6(1)(b))'),
            ('legitimate_interest', 'Законний інтерес (art. 6(1)(f))'),
            ('legal_obligation', 'Юридичний обовʼязок (art. 6(1)(c))'),
        ],
        string='Правова підстава',
        required=True,
        default='consent',
    )

    consent_given = fields.Boolean(
        string='Згода надана',
        required=True,
        default=True,
        index=True,
        help='True = клієнт дав згоду / надав contact-дані з метою отримати '
        'маркетинговий матеріал. False = відкликання згоди (unsubscribe).',
    )
    consent_timestamp = fields.Datetime(
        string='Час події',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    exact_user_response = fields.Text(
        string='Точна відповідь клієнта',
        help='Що БУКВАЛЬНО написав клієнт у чаті: email, телефон, «TAK», '
        '«Згоден», «STOP», «отписка». Юридичний доказ згоди.',
    )
    policy_version = fields.Char(
        string='Версія політики',
        help='Версія RODO/Polityka prywatności на момент надання згоди. '
        'Береться з ir.config_parameter `odoo_chatwoot_connector.rodo_policy_version`.',
    )
    source = fields.Selection(
        [
            ('sendpulse_chat', 'Чат SendPulse (автоматично з чату)'),
            ('website_form', 'Форма на сайті'),
            ('landing_form', 'Форма на лендінгу'),
            ('meta_lead_form', 'Meta Lead Ad (Facebook/Instagram)'),
            ('admin_manual', 'Ручне внесення адміном'),
            ('email_unsubscribe', 'Відписка від email-розсилки'),
            ('email_invalid', 'Невірна адреса електронної пошти'),
            ('api', 'API'),
        ],
        string='Джерело',
        required=True,
        default='sendpulse_chat',
        index=True,
    )

    display_name = fields.Char(
        string='Назва',
        compute='_compute_display_name',
        store=True,
    )

    notes = fields.Text(string='Коментар')

    @api.depends('partner_id', 'email', 'phone', 'purpose', 'consent_given', 'consent_timestamp')
    def _compute_display_name(self):
        for rec in self:
            who = rec.partner_id.name or rec.email or rec.phone or '—'
            action = '✅' if rec.consent_given else '🚫'
            ts = rec.consent_timestamp.strftime('%Y-%m-%d %H:%M') if rec.consent_timestamp else ''
            rec.display_name = f'{action} {who} — {rec.purpose or ""} [{ts}]'

    @api.model_create_multi
    def create(self, vals_list):
        # Policy version auto-fill якщо не передано
        policy = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('odoo_chatwoot_connector.rodo_policy_version', 'v1.0')
        )
        for vals in vals_list:
            if not vals.get('policy_version'):
                vals['policy_version'] = policy
        return super().create(vals_list)

    def write(self, vals):
        # Append-only: блокуємо зміну ключових полів. Дозволяємо тільки
        # notes редагувати (щоб адмін міг додати пояснення).
        protected = {
            'partner_id',
            'email',
            'phone',
            'purpose',
            'channel',
            'legal_basis',
            'consent_given',
            'consent_timestamp',
            'exact_user_response',
            'policy_version',
            'source',
            'message_id',
            'connect_id',
        }
        if protected & set(vals.keys()):
            raise models.UserError(
                self.env._(
                    'Записи у журналі згод RODO — append-only. '
                    'Щоб відкликати згоду — створіть новий запис з consent_given=False. '
                    'Редагувати можна тільки поле «Коментар».'
                )
            )
        return super().write(vals)

    def unlink(self):
        # Заборонено видаляти — це юридичний журнал. Тільки суперюзер
        # може знести (наприклад при GDPR-запиті «право на забуття»,
        # але краще архівувати через withdrawal запис).
        if not self.env.user._is_superuser():
            raise models.UserError(
                self.env._(
                    'Записи у журналі згод RODO не можна видаляти. '
                    'Для відкликання — створіть новий запис з consent_given=False.'
                )
            )
        return super().unlink()

    # ── API для виклику з flow ─────────────────────────────────────────────

    @api.model
    def record_consent(
        self,
        purpose,
        channel,
        partner_id=False,
        connect_id=False,
        message_id=False,
        email=False,
        phone=False,
        consent_given=True,
        exact_response='',
        legal_basis='consent',
        source='sendpulse_chat',
        notes='',
    ):
        """Helper для запису consent-події з flow-коду. Повертає створений запис."""
        vals = {
            'purpose': purpose,
            'channel': channel,
            'partner_id': partner_id or False,
            'connect_id': connect_id or False,
            'message_id': message_id or False,
            'email': (email or '').strip().lower() or False,
            'phone': (phone or '').strip() or False,
            'consent_given': bool(consent_given),
            'exact_user_response': exact_response or '',
            'legal_basis': legal_basis,
            'source': source,
            'notes': notes or '',
        }
        rec = self.sudo().create(vals)
        _logger.info(
            'RODO consent %s: purpose=%s channel=%s partner=%s email=%s phone=%s id=%s',
            'GRANTED' if consent_given else 'WITHDRAWN',
            purpose,
            channel,
            partner_id,
            email,
            phone,
            rec.id,
        )
        return rec

    @api.model
    def has_active_consent(self, purpose, email=False, phone=False, partner_id=False):
        """
        True якщо для цієї комбінації (email/phone/partner, purpose) є
        consent_given=True і НЕ має пізнішого withdrawal. Останній запис
        вирішує — надано чи відкликано.
        """
        domain = [('purpose', '=', purpose)]
        if email:
            domain.append(('email', '=', email.strip().lower()))
        elif phone:
            domain.append(('phone', '=', phone.strip()))
        elif partner_id:
            domain.append(('partner_id', '=', partner_id))
        else:
            return False
        last = self.sudo().search(domain, order='consent_timestamp desc, id desc', limit=1)
        return bool(last and last.consent_given)
