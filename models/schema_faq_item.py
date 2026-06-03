from odoo import fields, models


class MidvexSchemaFaqItem(models.Model):
    _name = 'midvex.schema.faq.item'
    _description = 'Midvex Schema FAQ Item'
    _rec_name = 'question'
    _order = 'position'

    schema_record_id = fields.Many2one(
        'midvex.schema.record', string='Schema Record',
        required=True, ondelete='cascade', index=True,
    )
    question = fields.Char('Question', required=True)
    answer = fields.Text('Answer', required=True)
    position = fields.Integer('Position', default=1)
    active = fields.Boolean('Active', default=True)
    lang_code = fields.Char('Language Code', help='e.g. en, no, de')
