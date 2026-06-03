import json
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MidvexSchemaFieldValue(models.Model):
    _name = 'midvex.schema.field.value'
    _description = 'Midvex Schema Field Value'
    _rec_name = 'field_key'
    _order = 'sequence, field_key'

    schema_record_id = fields.Many2one(
        'midvex.schema.record', string='Schema Record',
        required=True, ondelete='cascade', index=True,
    )
    field_key = fields.Char('Field Key', required=True,
                             help='JSON-LD property name, e.g. name, description, image')
    field_label = fields.Char('Label')
    field_type = fields.Selection([
        ('char', 'Text (single line)'),
        ('text', 'Text (multi-line)'),
        ('html', 'HTML'),
        ('json', 'JSON'),
        ('url', 'URL'),
        ('boolean', 'Boolean'),
        ('integer', 'Integer'),
        ('float', 'Float'),
    ], string='Field Type', default='char', required=True)
    value_char = fields.Char('Value (Char)')
    value_text = fields.Text('Value (Text)')
    value_html = fields.Html('Value (HTML)', sanitize=True)
    value_json = fields.Text('Value (JSON)')
    value_url = fields.Char('Value (URL)')
    value_boolean = fields.Boolean('Value (Boolean)')
    value_integer = fields.Integer('Value (Integer)')
    value_float = fields.Float('Value (Float)')
    lang_code = fields.Char('Language Code', help='e.g. en, no, de')
    required = fields.Boolean('Required')
    sequence = fields.Integer('Sequence', default=10)

    def get_value(self):
        self.ensure_one()
        if self.field_type == 'char':
            return self.value_char
        if self.field_type == 'text':
            return self.value_text
        if self.field_type == 'html':
            return self.value_html
        if self.field_type == 'json':
            return self._parse_json_value()
        if self.field_type == 'url':
            return self.value_url
        if self.field_type == 'boolean':
            return self.value_boolean
        if self.field_type == 'integer':
            return self.value_integer
        if self.field_type == 'float':
            return self.value_float
        return None

    def _parse_json_value(self):
        if not self.value_json:
            return None
        try:
            return json.loads(self.value_json)
        except (json.JSONDecodeError, TypeError):
            return None

    @api.constrains('field_type', 'value_json')
    def _check_value_json(self):
        for rec in self:
            if rec.field_type == 'json' and rec.value_json:
                try:
                    json.loads(rec.value_json)
                except (json.JSONDecodeError, TypeError):
                    raise ValidationError(
                        f'Field "{rec.field_key}": JSON value must be valid JSON.'
                    )
