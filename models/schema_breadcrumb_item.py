from odoo import fields, models


class MidvexSchemaBreadcrumbItem(models.Model):
    _name = 'midvex.schema.breadcrumb.item'
    _description = 'Midvex Schema Breadcrumb Item'
    _order = 'position'

    schema_record_id = fields.Many2one(
        'midvex.schema.record', string='Schema Record',
        required=True, ondelete='cascade', index=True,
    )
    name = fields.Char('Name', required=True)
    url = fields.Char('URL', required=True)
    position = fields.Integer('Position', default=1)
    lang_code = fields.Char('Language Code', help='e.g. en, no, de')
