from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SendpulseFaqEntry(models.Model):
    _name = 'sendpulse.faq.entry'
    _description = 'FAQ Entry — для RAG auto-answer клієнтам'
    _order = 'priority desc, hit_count desc, id'
    _rec_name = 'name'

    name = fields.Char(
        string='Назва (коротко)',
        required=True,
        translate=True,
        help='Коротка назва для списку, напр. "Питання про ціну"',
    )
    question = fields.Text(
        string='Питання (шаблон)',
        required=True,
        translate=True,
        help='Типове формулювання питання клієнта. LLM зматчить сюди різні варіації.',
    )
    answer = fields.Text(
        string='Відповідь',
        required=True,
        translate=True,
        help="Канонічна відповідь. LLM персоналізує її (добавить ім'я клієнта тощо) перед відправкою.",
    )
    tags = fields.Char(
        string='Теги',
        help='Comma-separated, напр. "price,summer,discount". Для фільтрації у list view.',
    )
    priority = fields.Integer(
        string='Пріоритет',
        default=10,
        help='Вищий = важливіший. При матчі кількох FAQ бере з вищим priority.',
    )
    active = fields.Boolean(
        string='Активний',
        default=True,
        help='Неактивні не беруть участі в RAG-підборі.',
    )
    hit_count = fields.Integer(
        string='Використано разів',
        default=0,
        readonly=True,
        help='Скільки разів цей FAQ був обраний для відповіді. Оновлюється автоматично.',
    )
    last_used_at = fields.Datetime(
        string='Останнє використання',
        readonly=True,
    )

    @api.model
    def get_active_faq_for_prompt(self):
        """
        Повертає список активних FAQ у форматі для LLM prompt.
        Return: list of dict {id, question, answer}

        Lang пінується на en_US (source): база знань бота не повинна
        залежати від мови залогіненого оператора, який викликав RAG.
        """
        records = (
            self.with_context(lang='en_US').search([('active', '=', True)], order='priority desc')
        )
        return [{'id': r.id, 'question': r.question, 'answer': r.answer} for r in records]

    def action_test_match(self):
        """Wizard для тестування чи LLM би обрав саме цей FAQ на тестовий ввід."""
        self.ensure_one()
        raise UserError(
            _(
                'Test-match wizard поки не реалізований. '
                'Скористайтесь odoo shell:\n'
                "env['sendpulse.connect']._rag_answer_question('Ваше тестове питання')"
            )
        )
