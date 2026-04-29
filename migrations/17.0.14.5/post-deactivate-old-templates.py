"""Деактивує старі v1 публічні шаблони (public_template_1..5) при upgrade на 17.0.14.5.

Контекст: Meta App Review для pages_messaging ще не approved (станом на 2026-04-29),
тому FB private_replies провалюється з 100/33. v1 шаблони обіцяли клієнту приватну
відповідь, якої він не отримує. v2 шаблони чесно говорять «пишіть тут, ми 24/7».

Repeat-шаблон (public_template_repeat) залишаємо активним — він не обіцяє приват.
"""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE sendpulse_public_template
        SET active = false
        WHERE id IN (
            SELECT res_id FROM ir_model_data
            WHERE module = 'odoo_chatwoot_connector'
              AND name IN (
                  'public_template_1',
                  'public_template_2',
                  'public_template_3',
                  'public_template_4',
                  'public_template_5'
              )
        )
        """
    )
