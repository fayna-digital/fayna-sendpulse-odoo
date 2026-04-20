# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── SendPulse OAuth ─────────────────────────────────────────────────
    sendpulse_client_id = fields.Char(
        string='SendPulse Client ID',
        config_parameter='odoo_chatwoot_connector.client_id',
        help='Знайти в SendPulse: Settings → API → Client ID',
    )
    sendpulse_client_secret = fields.Char(
        string='SendPulse Client Secret',
        help='Залиште порожнім щоб не змінювати поточне значення',
    )
    sendpulse_secret_is_set = fields.Boolean(
        compute='_compute_sendpulse_secret_is_set',
    )
    sendpulse_webhook_token = fields.Char(
        string='Webhook Secret Token',
        config_parameter='odoo_chatwoot_connector.webhook_token',
        help='Довільний секретний рядок для перевірки запитів від SendPulse',
    )

    # ── Webhook URL (тільки для читання — для копіювання) ───────────────
    sendpulse_webhook_url = fields.Char(
        string='Webhook URL (скопіюйте в SendPulse)',
        compute='_compute_webhook_url',
        readonly=True,
    )

    @api.depends('sendpulse_client_secret')
    def _compute_sendpulse_secret_is_set(self):
        secret = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_chatwoot_connector.client_secret', ''
        )
        for rec in self:
            rec.sendpulse_secret_is_set = bool(secret)

    @api.depends('sendpulse_webhook_token')
    def _compute_webhook_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            rec.sendpulse_webhook_url = f"{base_url}/sendpulse/webhook"

    # ── SendPulse — Відповіді на коментарі ──────────────────────────────
    sp_comment_autoreply_enabled = fields.Boolean(
        string='Автовідповідь на коментарі FB/IG',
        config_parameter='odoo_chatwoot_connector.sp_comment_autoreply_enabled',
        default=True,
    )
    sp_comment_public_enabled = fields.Boolean(
        string='Публічна відповідь під коментарем',
        config_parameter='odoo_chatwoot_connector.sp_comment_public_enabled',
        default=True,
    )
    sp_comment_private_enabled = fields.Boolean(
        string='Приватне повідомлення (перший коментар)',
        config_parameter='odoo_chatwoot_connector.sp_comment_private_enabled',
        default=True,
    )
    fb_page_access_token = fields.Char(
        string='Facebook Page Access Token',
        help='Безстроковий Page Access Token з Facebook Developer Portal. '
             'Потрібен для публікації відповідей на коментарі та private_replies.',
    )
    fb_page_token_is_set = fields.Boolean(
        compute='_compute_fb_page_token_is_set',
    )
    fb_app_id = fields.Char(
        string='Facebook App ID',
        config_parameter='odoo_chatwoot_connector.fb_app_id',
        help='App ID з Meta Developer Portal. Потрібен для перевірки терміну дії токена (/debug_token).',
    )
    fb_app_secret = fields.Char(
        string='Facebook App Secret',
        help='App Secret з Meta Developer Portal. Потрібен для /debug_token. Залиште порожнім щоб не змінювати.',
    )
    fb_app_secret_is_set = fields.Boolean(
        compute='_compute_fb_app_secret_is_set',
    )
    fb_token_status = fields.Char(
        string='Статус Page Token',
        compute='_compute_fb_token_status',
        readonly=True,
        help='Стан валідності і термін дії. Оновлюється щотижнево через cron.',
    )
    fb_token_last_check = fields.Char(
        string='Остання перевірка',
        compute='_compute_fb_token_status',
        readonly=True,
    )
    ig_user_id = fields.Char(
        string='Instagram Business Account ID',
        help='Числовий ID Instagram Business Account (~15 цифр). '
             'Потрібен для private_reply на коментарі Instagram. '
             'Отримати: GET /me?fields=instagram_business_account з Page Token.',
    )
    ig_user_id_is_set = fields.Boolean(
        compute='_compute_ig_user_id_is_set',
    )
    sp_comment_landing_url = fields.Char(
        string='URL лендінгу (у публічних відповідях)',
        config_parameter='odoo_chatwoot_connector.sp_comment_landing_url',
        default='https://lato2026.campscout.eu',
        help='Підставляється як {landing_url} у шаблони публічних відповідей',
    )
    sp_comment_tg_url = fields.Char(
        string='URL Telegram-каналу',
        config_parameter='odoo_chatwoot_connector.sp_comment_tg_url',
        default='https://t.me/campscouting',
        help='Підставляється як {tg_url} у шаблони публічних відповідей',
    )
    sp_comment_yt_url = fields.Char(
        string='URL YouTube-плейлисту',
        config_parameter='odoo_chatwoot_connector.sp_comment_yt_url',
        default='https://www.youtube.com/playlist?list=PLgc9vcdbFyLQZaeghL7ffKVr2P4y4aVHV',
        help='Підставляється як {yt_url} у шаблон приватного повідомлення',
    )
    sp_comment_private_text = fields.Char(
        string='Текст приватного повідомлення',
        config_parameter='odoo_chatwoot_connector.sp_comment_private_text',
        help='Шаблон приватного повідомлення. Доступні змінні: {landing_url}, {tg_url}, {yt_url}. '
             'Залиште порожнім щоб використовувати дефолтний текст.',
    )

    # ── LLM-класифікатор коментарів ─────────────────────────────────────
    llm_classifier_enabled = fields.Boolean(
        string='LLM-класифікатор коментарів',
        config_parameter='odoo_chatwoot_connector.llm_classifier_enabled',
        default=False,
        help='Класифікує коментарі (питання/подяка/скарга/спам) через Anthropic Claude. '
             'На подяки і спам автовідповідь не надсилаємо, скарги ескалуємо оператору.',
    )
    anthropic_api_key = fields.Char(
        string='Anthropic API Key',
        help='API-ключ з console.anthropic.com для LLM-класифікації. Залиште порожнім щоб не змінювати.',
    )
    anthropic_api_key_is_set = fields.Boolean(
        compute='_compute_anthropic_api_key_is_set',
    )
    llm_model = fields.Char(
        string='LLM Model',
        config_parameter='odoo_chatwoot_connector.llm_model',
        default='claude-haiku-4-5',
        help='Ідентифікатор моделі Anthropic. За замовчуванням claude-haiku-4-5 (найдешевша, ~$0.20/1000 коментарів).',
    )
    sp_comment_hide_spam_enabled = fields.Boolean(
        string='Автоматично приховувати спам-коментарі',
        config_parameter='odoo_chatwoot_connector.sp_comment_hide_spam_enabled',
        default=True,
        help='Якщо LLM-класифікатор позначив коментар як spam — автоматично ховаємо через Graph API (is_hidden=true).',
    )

    # ── Sync from Meta (для Multi-page) ─────────────────────────────────
    fb_sync_user_token = fields.Char(
        string='User Access Token (тимчасово)',
        help='Короткоживучий User Token з Graph API Explorer з permissions '
             'pages_show_list + business_management. Не зберігається — '
             'використовується тільки для одноразового виклику /me/accounts.',
    )
    fb_pages_count = fields.Integer(
        string='Зареєстрованих Pages',
        compute='_compute_fb_pages_count',
    )

    @api.depends('fb_sync_user_token')
    def _compute_fb_pages_count(self):
        count = self.env['sendpulse.facebook.page'].sudo().search_count([('active', '=', True)])
        for rec in self:
            rec.fb_pages_count = count

    def action_sync_fb_pages(self):
        """Синхронізує Facebook Pages з Meta через введений User Token."""
        self.ensure_one()
        if not self.fb_sync_user_token:
            from odoo.exceptions import UserError
            raise UserError(_('Введіть User Access Token перш ніж синхронізувати.'))
        Page = self.env['sendpulse.facebook.page'].sudo()
        processed = Page.sync_from_meta(self.fb_sync_user_token)
        created = sum(1 for _p, action in processed if action == 'created')
        updated = sum(1 for _p, action in processed if action == 'updated')
        # Очищаємо поле щоб токен не залишався у формі
        self.fb_sync_user_token = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Синхронізація завершена'),
                'message': _('Створено: %d, оновлено: %d з %d сторінок') % (created, updated, len(processed)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ── Auto-archive old comments (V2 F7) ────────────────────────────────
    auto_archive_comments_enabled = fields.Boolean(
        string='Авто-архівація старих коментарів',
        config_parameter='odoo_chatwoot_connector.auto_archive_comments_enabled',
        default=False,
        help='Soft-archive (active=False) для закритих comment-розмов старших '
             'за N днів. Запис залишається у БД, але ховається з default views.',
    )
    auto_archive_comments_days = fields.Integer(
        string='Дні до архівації',
        config_parameter='odoo_chatwoot_connector.auto_archive_comments_days',
        default=30,
        help='Скільки днів має пройти з write_date щоб закритий коментарний запис був архівований.',
    )

    # ── Auto-refresh FB tokens (V2 F6) ───────────────────────────────────
    auto_refresh_tokens_enabled = fields.Boolean(
        string='Авто-refresh FB Page tokens',
        config_parameter='odoo_chatwoot_connector.auto_refresh_tokens_enabled',
        default=False,
        help='Коли Page Token помирає < N днів — exchange на long-lived через '
             '/oauth/access_token?grant_type=fb_exchange_token. Потребує app_id + app_secret.',
    )
    token_refresh_threshold_days = fields.Integer(
        string='Поріг refresh (днів)',
        config_parameter='odoo_chatwoot_connector.token_refresh_threshold_days',
        default=14,
        help='Refresh токен якщо залишилось менше N днів. Дефолт 14.',
    )

    # ── Bot-wizard ідентифікації (V2 F3) ─────────────────────────────────
    bot_identification_enabled = fields.Boolean(
        string='Bot auto-ідентифікація',
        config_parameter='odoo_chatwoot_connector.bot_identification_enabled',
        default=False,
        help='Коли прийшло повідомлення від невідомого контакту — бот автоматично '
             'питає email. На наступний inbound парсить email з тексту і створює '
             'res.partner. Якщо клієнт не надає email за N спроб — передача оператору.',
    )
    bot_identification_max_attempts = fields.Integer(
        string='Max спроб email',
        config_parameter='odoo_chatwoot_connector.bot_identification_max_attempts',
        default=3,
        help='Скільки разів бот просить email перш ніж передати оператору.',
    )

    # ── RAG FAQ auto-answer (V2 F1) ──────────────────────────────────────
    rag_auto_answer_enabled = fields.Boolean(
        string='RAG FAQ авто-відповідь',
        config_parameter='odoo_chatwoot_connector.rag_auto_answer_enabled',
        default=False,
        help='Коли клієнт пише питання у приват — модуль шукає match у FAQ '
             'через Claude. Якщо confidence > threshold — шле автоматичну відповідь. '
             'Потребує anthropic_api_key + FAQ записи у меню SendPulse → FAQ Entries.',
    )
    rag_auto_confidence_threshold = fields.Float(
        string='Поріг confidence',
        config_parameter='odoo_chatwoot_connector.rag_auto_confidence_threshold',
        default=0.85,
        help='0.0-1.0. Нижче цього значення — модуль НЕ відповідає автоматично, '
             'передає оператору. Високий threshold (0.85+) = мало false positives.',
    )

    # ── Weekly Telegram report (V2 F8) ───────────────────────────────────
    weekly_report_enabled = fields.Boolean(
        string='Щотижневий Telegram-звіт',
        config_parameter='odoo_chatwoot_connector.weekly_report_enabled',
        default=False,
        help='Понеділок 09:00 UTC → у telegram-групу зводка за минулий тиждень: '
             'webhook-и по типах, категорії коментарів, funnel-конверсія, SLA, алерти.',
    )

    # ── Auto-close inactive (V2 F5) ──────────────────────────────────────
    auto_close_inactive_enabled = fields.Boolean(
        string='Авто-закриття неактивних розмов',
        config_parameter='odoo_chatwoot_connector.auto_close_inactive_enabled',
        default=False,
        help='Закриває розмови у stage in_progress/new_message якщо клієнт '
             'не писав X днів. Cron 1 раз/добу.',
    )
    auto_close_inactive_days = fields.Integer(
        string='Дні до авто-закриття',
        config_parameter='odoo_chatwoot_connector.auto_close_inactive_days',
        default=7,
        help='Скільки днів бездіяльності перш ніж закрити. Дефолт 7.',
    )
    auto_close_goodbye_text = fields.Char(
        string='Прощальне повідомлення (опц.)',
        config_parameter='odoo_chatwoot_connector.auto_close_goodbye_text',
        help='Якщо задано і 24h-вікно Meta відкрите — надсилається клієнту '
             'при авто-закритті. Залиште порожнім щоб не надсилати.',
    )

    # ── Auto-create CRM leads (V2 F4) ────────────────────────────────────
    auto_create_lead_enabled = fields.Boolean(
        string='Автоматично створювати ліди',
        config_parameter='odoo_chatwoot_connector.auto_create_lead_enabled',
        default=False,
        help='Коли клієнт відповів у приват (funnel_stage=customer_replied) — '
             'автоматично створюється crm.lead зі знайденим партнером і прив\'язується '
             'до розмови через sp_lead_id. Ідемпотентно — якщо лід уже є, не створює другий.',
    )
    auto_create_lead_team_id = fields.Many2one(
        'crm.team',
        string='Sales team для авто-лідів',
        config_parameter='odoo_chatwoot_connector.auto_create_lead_team_id',
        help='Якщо не задано — використовується default команда із CRM.',
    )

    # ── Telegram-алерти менеджерам ──────────────────────────────────────
    telegram_alerts_enabled = fields.Boolean(
        string='Telegram-алерти менеджерам',
        config_parameter='odoo_chatwoot_connector.telegram_alerts_enabled',
        default=False,
        help='Надсилати критичні сповіщення у Telegram-групу менеджерів: скарги, прихований спам, проблеми з токеном.',
    )
    telegram_bot_token = fields.Char(
        string='Telegram Bot Token',
        help='Токен з @BotFather (формат: 7123456789:AAEr...). Залиште порожнім щоб не змінювати.',
    )
    telegram_bot_token_is_set = fields.Boolean(
        compute='_compute_telegram_bot_token_is_set',
    )
    telegram_chat_id = fields.Char(
        string='Telegram Chat ID',
        config_parameter='odoo_chatwoot_connector.telegram_chat_id',
        help="ID групи куди бот пише. Для груп — від'ємне число (-1001234567890). Отримати через /getUpdates після додавання бота в групу.",
    )

    @api.depends('fb_page_access_token')
    def _compute_fb_page_token_is_set(self):
        token = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_chatwoot_connector.fb_page_access_token', ''
        )
        for rec in self:
            rec.fb_page_token_is_set = bool(token)

    @api.depends('ig_user_id')
    def _compute_ig_user_id_is_set(self):
        val = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_chatwoot_connector.ig_user_id', ''
        )
        for rec in self:
            rec.ig_user_id_is_set = bool(val)

    @api.depends('fb_app_secret')
    def _compute_fb_app_secret_is_set(self):
        val = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_chatwoot_connector.fb_app_secret', ''
        )
        for rec in self:
            rec.fb_app_secret_is_set = bool(val)

    @api.depends('fb_page_access_token')
    def _compute_fb_token_status(self):
        ICP = self.env['ir.config_parameter'].sudo()
        status = ICP.get_param('odoo_chatwoot_connector.fb_token_status', 'not_checked')
        last = ICP.get_param('odoo_chatwoot_connector.fb_token_last_check', '')
        for rec in self:
            rec.fb_token_status = status
            rec.fb_token_last_check = last

    @api.depends('anthropic_api_key')
    def _compute_anthropic_api_key_is_set(self):
        val = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_chatwoot_connector.anthropic_api_key', ''
        )
        for rec in self:
            rec.anthropic_api_key_is_set = bool(val)

    @api.depends('telegram_bot_token')
    def _compute_telegram_bot_token_is_set(self):
        val = self.env['ir.config_parameter'].sudo().get_param(
            'odoo_chatwoot_connector.telegram_bot_token', ''
        )
        for rec in self:
            rec.telegram_bot_token_is_set = bool(val)

    def get_values(self):
        # sendpulse_client_secret навмисно не повертається:
        # поле завжди завантажується порожнім (False == False → не dirty).
        # Реальне значення зберігається/читається через set_values / ir.config_parameter.
        return super().get_values()

    def set_values(self):
        super().set_values()
        if self.sendpulse_client_secret:
            self.env['ir.config_parameter'].sudo().set_param(
                'odoo_chatwoot_connector.client_secret',
                self.sendpulse_client_secret,
            )
        if self.fb_page_access_token:
            self.env['ir.config_parameter'].sudo().set_param(
                'odoo_chatwoot_connector.fb_page_access_token',
                self.fb_page_access_token,
            )
        if self.ig_user_id:
            self.env['ir.config_parameter'].sudo().set_param(
                'odoo_chatwoot_connector.ig_user_id',
                self.ig_user_id,
            )
        if self.fb_app_secret:
            self.env['ir.config_parameter'].sudo().set_param(
                'odoo_chatwoot_connector.fb_app_secret',
                self.fb_app_secret,
            )
        if self.anthropic_api_key:
            self.env['ir.config_parameter'].sudo().set_param(
                'odoo_chatwoot_connector.anthropic_api_key',
                self.anthropic_api_key,
            )
        if self.telegram_bot_token:
            self.env['ir.config_parameter'].sudo().set_param(
                'odoo_chatwoot_connector.telegram_bot_token',
                self.telegram_bot_token,
            )
