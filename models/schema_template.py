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
    load_optional_fields_by_default = fields.Boolean(
        'Load optional fields by default',
        help='Create optional field rows automatically when this template is selected.',
    )
    required_field_count = fields.Integer(
        'Required Fields', compute='_compute_field_counts', store=False
    )
    optional_field_count = fields.Integer(
        'Optional Fields', compute='_compute_field_counts', store=False
    )

    def _compute_field_counts(self):
        for rec in self:
            rec.required_field_count = len(rec.get_required_fields())
            rec.optional_field_count = len(rec.get_optional_fields())

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

    def _json_field_names(self):
        return [
            'json_template',
            'required_fields_json',
            'optional_fields_json',
            'auto_mapping_json',
            'validation_rules_json',
        ]

    def action_format_json_fields(self):
        for rec in self:
            vals = {}
            for fname in rec._json_field_names():
                raw = getattr(rec, fname)
                if not raw:
                    continue
                parsed = json.loads(raw)
                vals[fname] = json.dumps(parsed, ensure_ascii=False, indent=2)
            if vals:
                rec.write(vals)
        return True

    def action_validate_json_fields(self):
        self._check_json_fields()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'JSON is valid',
                'message': 'All template JSON fields are valid.',
                'type': 'success',
                'sticky': False,
            },
        }

    def get_recommended_target_type(self):
        self.ensure_one()
        if self.schema_type in ('Organization', 'WebSite'):
            return 'global'
        if self.schema_type in ('LocalBusiness',):
            return 'global'
        if self.schema_type in (
            'Product', 'FAQPage', 'BreadcrumbList', 'Article', 'BlogPosting',
            'ContactPage', 'AboutPage', 'Service', 'CollectionPage',
        ):
            return 'page'
        return 'page'

    @api.constrains('json_template', 'required_fields_json', 'optional_fields_json',
                    'auto_mapping_json', 'validation_rules_json')
    def _check_json_fields(self):
        json_fields = [
            ('json_template', 'Default JSON Structure', dict),
            ('required_fields_json', 'Required Fields', list),
            ('optional_fields_json', 'Optional Fields', list),
            ('auto_mapping_json', 'Auto-fill Mapping', dict),
            ('validation_rules_json', 'Validation Rules', dict),
        ]
        for rec in self:
            for fname, label, expected_type in json_fields:
                val = getattr(rec, fname)
                if val:
                    try:
                        parsed = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        raise ValidationError(f'"{label}" must contain valid JSON.')
                    if not isinstance(parsed, expected_type):
                        raise ValidationError(
                            f'"{label}" must be a JSON {expected_type.__name__}.'
                        )

    def unlink(self):
        for rec in self:
            if rec.is_system_template:
                raise ValidationError(
                    f'System template "{rec.name}" cannot be deleted. Deactivate it instead.'
                )
        return super().unlink()

    def action_duplicate_template(self):
        self.ensure_one()
        new_template = self.copy({
            'name': '%s (Copy)' % self.name,
            'is_system_template': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Template Library',
            'res_model': 'midvex.schema.template',
            'view_mode': 'form',
            'res_id': new_template.id,
            'target': 'current',
        }

    def action_use_template(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Page Schema',
            'res_model': 'midvex.schema.record',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_schema_template_id': self.id,
                'default_schema_type': self.schema_type,
                'default_target_type': self.get_recommended_target_type(),
                'default_name': self.name,
            },
        }
