import json
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MidvexSchemaTemplate(models.Model):
    _name = 'midvex.schema.template'
    _description = 'Midvex Schema Template'
    _order = 'sequence, name'

    name = fields.Char('Template Name', required=True)
    schema_type = fields.Char('Schema Type', required=True,
                               help='e.g. Organization, Product, FAQPage')
    description = fields.Text('Description')
    json_template = fields.Text('Default JSON Structure', default='{}')
    required_fields_json = fields.Text('Required Fields', default='[]',
                                        help='JSON array of required field keys')
    optional_fields_json = fields.Text('Optional Fields', default='[]',
                                        help='JSON array of optional field keys')
    auto_mapping_json = fields.Text('Auto-fill Mapping', default='{}',
                                     help='JSON map: schema_field -> odoo_metadata_field')
    validation_rules_json = fields.Text('Validation Rules', default='{}')
    active = fields.Boolean('Active', default=True)
    sequence = fields.Integer('Sequence', default=10)
    is_system_template = fields.Boolean('System Template', default=False,
                                         help='System templates cannot be deleted')

    def get_default_structure(self):
        self.ensure_one()
        try:
            return json.loads(self.json_template or '{}')
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_required_fields(self):
        self.ensure_one()
        try:
            return json.loads(self.required_fields_json or '[]')
        except (json.JSONDecodeError, TypeError):
            return []

    def get_optional_fields(self):
        self.ensure_one()
        try:
            return json.loads(self.optional_fields_json or '[]')
        except (json.JSONDecodeError, TypeError):
            return []

    def get_auto_mapping(self):
        self.ensure_one()
        try:
            return json.loads(self.auto_mapping_json or '{}')
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_validation_rules(self):
        self.ensure_one()
        try:
            return json.loads(self.validation_rules_json or '{}')
        except (json.JSONDecodeError, TypeError):
            return {}

    @api.constrains('json_template', 'required_fields_json', 'optional_fields_json',
                    'auto_mapping_json', 'validation_rules_json')
    def _check_json_fields(self):
        json_fields = [
            ('json_template', 'Default JSON Structure'),
            ('required_fields_json', 'Required Fields'),
            ('optional_fields_json', 'Optional Fields'),
            ('auto_mapping_json', 'Auto-fill Mapping'),
            ('validation_rules_json', 'Validation Rules'),
        ]
        for rec in self:
            for fname, label in json_fields:
                val = getattr(rec, fname)
                if val:
                    try:
                        json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        raise ValidationError(f'"{label}" must contain valid JSON.')

    def unlink(self):
        for rec in self:
            if rec.is_system_template:
                raise ValidationError(
                    f'System template "{rec.name}" cannot be deleted. Deactivate it instead.'
                )
        return super().unlink()
