from odoo import api, fields, models

from .schema_record import _infer_schema_field_type, _set_nested_value


class MidvexSchemaMapping(models.Model):
    _name = 'midvex.schema.mapping'
    _description = 'Midvex Schema Model Mapping'
    _order = 'name'

    name = fields.Char(required=True)
    target_model = fields.Char(required=True, help='Odoo model technical name, e.g. product.template')
    schema_template_id = fields.Many2one('midvex.schema.template', string='Schema Template')
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('midvex.schema.mapping.line', 'mapping_id', string='Mapping Lines')

    @api.model
    def _safe_read_field(self, record, field_name):
        if not record or not getattr(record, 'exists', lambda: False)():
            return ''
        if field_name not in record._fields:
            return ''
        value = record[field_name]
        if hasattr(value, 'display_name'):
            return value.display_name
        return value

    def build_schema_data(self, target_record, context=None):
        self.ensure_one()
        context = dict(context or {})
        if self.target_model and target_record._name != self.target_model:
            return {}
        data = self.schema_template_id.get_default_structure() if self.schema_template_id else {}
        token_service = self.env['midvex.schema.token']
        for line in self.line_ids.sorted('sequence'):
            value = line.default_value or ''
            if line.source_type == 'token':
                value, _warnings = token_service.resolve_tokens(line.token or '', context=context)
            elif line.source_type == 'odoo_field':
                value = self._safe_read_field(target_record, line.odoo_field_name or '')
            elif line.source_type == 'computed':
                value, _warnings = token_service.resolve_tokens(line.token or line.default_value or '', context=context)
            if value not in (None, False, ''):
                _set_nested_value(data, line.schema_field_path, value)
        if self.schema_template_id:
            data.setdefault('@context', 'https://schema.org')
            data.setdefault('@type', self.schema_template_id.schema_type)
        return data


class MidvexSchemaMappingLine(models.Model):
    _name = 'midvex.schema.mapping.line'
    _description = 'Midvex Schema Mapping Line'
    _order = 'sequence, schema_field_path'

    mapping_id = fields.Many2one('midvex.schema.mapping', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    schema_field_path = fields.Char(required=True)
    source_type = fields.Selection([
        ('manual', 'Manual / Default'),
        ('token', 'Token'),
        ('odoo_field', 'Odoo Field'),
        ('computed', 'Computed'),
    ], required=True, default='token')
    token = fields.Char()
    odoo_field_name = fields.Char()
    default_value = fields.Char()
    required = fields.Boolean()
    field_type = fields.Selection([
        ('char', 'Text (single line)'),
        ('text', 'Text (multi-line)'),
        ('html', 'HTML'),
        ('json', 'JSON'),
        ('url', 'URL'),
        ('boolean', 'Boolean'),
        ('integer', 'Integer'),
        ('float', 'Float'),
    ], default='char', required=True)

    @api.onchange('schema_field_path')
    def _onchange_schema_field_path(self):
        for line in self:
            if line.schema_field_path:
                line.field_type = _infer_schema_field_type(line.schema_field_path)
