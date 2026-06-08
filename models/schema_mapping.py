from odoo import api, fields, models, Command
from odoo.exceptions import ValidationError

from .schema_record import _infer_schema_field_type, _set_nested_value


class MidvexSchemaMapping(models.Model):
    _name = 'midvex.schema.mapping'
    _description = 'Midvex Schema Model Mapping'
    _order = 'name'

    name = fields.Char(required=True)
    target_model_id = fields.Many2one(
        'ir.model', string='Target Model', required=True, ondelete='cascade',
        domain="[('transient', '=', False)]",
        help='Odoo model to map, e.g. Product Template, Blog Post, Website Page, or a custom model.'
    )
    target_model = fields.Char(
        string='Target Model Technical Name',
        compute='_compute_target_model', store=True
    )
    schema_template_id = fields.Many2one('midvex.schema.template', string='Schema Template', required=True)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('midvex.schema.mapping.line', 'mapping_id', string='Mapping Lines')

    @api.depends('target_model_id')
    def _compute_target_model(self):
        for rec in self:
            rec.target_model = rec.target_model_id.model if rec.target_model_id else ''

    @api.onchange('target_model_id')
    def _onchange_target_model_id(self):
        if not self.target_model_id:
            return
        model_name = self.target_model_id.model
        template = self.env['midvex.schema.template']
        if model_name == 'product.template':
            template = self.env['midvex.schema.template'].search([('schema_type', '=', 'Product')], limit=1)
        elif model_name == 'blog.post':
            template = self.env['midvex.schema.template'].search([('schema_type', '=', 'BlogPosting')], limit=1)
        elif model_name == 'website.page':
            template = self.env['midvex.schema.template'].search([('schema_type', '=', 'WebPage')], limit=1)
            
        if template:
            self.schema_template_id = template

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'target_model' in vals and isinstance(vals['target_model'], str):
                model_rec = self.env['ir.model'].search([('model', '=', vals['target_model'])], limit=1)
                vals['target_model_id'] = model_rec.id if model_rec else False
                # Do not write string to target_model directly if it's computed/stored
                del vals['target_model']
            self._resolve_nested_line_field_names(vals)
        return super().create(vals_list)

    def write(self, vals):
        if 'target_model' in vals and isinstance(vals['target_model'], str):
            model_rec = self.env['ir.model'].search([('model', '=', vals['target_model'])], limit=1)
            vals['target_model_id'] = model_rec.id if model_rec else False
            del vals['target_model']
        self._resolve_nested_line_field_names(vals)
        return super().write(vals)

    def _resolve_nested_line_field_names(self, vals):
        model_id = vals.get('target_model_id')
        if not model_id and self:
            model_id = self[:1].target_model_id.id
        if not model_id or not vals.get('line_ids'):
            return
        line_model = self.env['midvex.schema.mapping.line']
        for command in vals.get('line_ids') or []:
            if not isinstance(command, (list, tuple)) or len(command) < 3:
                continue
            if command[0] == Command.CREATE and isinstance(command[2], dict):
                line_model._resolve_field_name(command[2], model_id)

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
        target_name = self.target_model_id.model if self.target_model_id else self.target_model
        if target_name and target_record._name != target_name:
            return {}
        data = self.schema_template_id.get_default_structure() if self.schema_template_id else {}
        token_service = self.env['midvex.schema.token']
        for line in self.line_ids.sorted('sequence'):
            value = line.default_value or ''
            if line.source_type == 'token':
                value, _warnings = token_service.resolve_tokens(line.token or '', context=context)
            elif line.source_type == 'odoo_field':
                field_name = line.odoo_field_id.name if line.odoo_field_id else line.odoo_field_name
                value = self._safe_read_field(target_record, field_name or '')
            elif line.source_type == 'computed':
                value, _warnings = token_service.resolve_tokens(line.token or line.default_value or '', context=context)
            if value not in (None, False, ''):
                _set_nested_value(data, line.schema_field_path, value)
        if self.schema_template_id:
            data.setdefault('@context', 'https://schema.org')
            data.setdefault('@type', self.schema_template_id.schema_type)
        return data

    def action_load_template_fields(self):
        self.ensure_one()
        if not self.schema_template_id:
            raise ValidationError("Please select a Schema Template first.")
        
        required_fields = self.schema_template_id.get_required_fields()
        optional_fields = self.schema_template_id.get_optional_fields()
        
        existing_paths = {line.schema_field_path for line in self.line_ids}
        
        new_lines = []
        for field in required_fields:
            if field not in existing_paths:
                new_lines.append((0, 0, {
                    'schema_field_path': field,
                    'required': True,
                    'source_type': 'token',
                    'field_type': _infer_schema_field_type(field),
                }))
                existing_paths.add(field)
                
        for field in optional_fields:
            if field not in existing_paths:
                new_lines.append((0, 0, {
                    'schema_field_path': field,
                    'required': False,
                    'source_type': 'token',
                    'field_type': _infer_schema_field_type(field),
                }))
                existing_paths.add(field)
                
        if new_lines:
            self.write({'line_ids': new_lines})
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Fields Loaded',
                'message': 'Successfully loaded template fields.',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_load_sample_mapping(self):
        self.ensure_one()
        if not self.target_model_id:
            raise ValidationError("Please select a Target Model first.")
            
        model_name = self.target_model_id.model
        template = self.env['midvex.schema.template']
        lines_vals = []
        
        def find_field(fname):
            return self.env['ir.model.fields'].search([
                ('model_id', '=', self.target_model_id.id),
                ('name', '=', fname)
            ], limit=1)
            
        if model_name == 'product.template':
            template = self.env['midvex.schema.template'].search([('schema_type', '=', 'Product')], limit=1)
            f_name = find_field('name')
            f_desc = find_field('description_sale') or find_field('description')
            f_price = find_field('list_price')
            
            lines_vals = [
                {'schema_field_path': 'name', 'source_type': 'odoo_field', 'odoo_field_id': f_name.id, 'field_type': 'char'},
                {'schema_field_path': 'description', 'source_type': 'odoo_field', 'odoo_field_id': f_desc.id, 'field_type': 'text'},
                {'schema_field_path': 'image', 'source_type': 'token', 'token': '{{ product.image_url }}', 'field_type': 'url'},
                {'schema_field_path': 'offers.price', 'source_type': 'odoo_field', 'odoo_field_id': f_price.id, 'field_type': 'float'},
                {'schema_field_path': 'offers.priceCurrency', 'source_type': 'token', 'token': '{{ product.currency }}', 'field_type': 'char'},
                {'schema_field_path': 'offers.availability', 'source_type': 'manual', 'default_value': 'https://schema.org/InStock', 'field_type': 'url'},
            ]
        elif model_name == 'blog.post':
            template = self.env['midvex.schema.template'].search([('schema_type', '=', 'BlogPosting')], limit=1)
            f_name = find_field('name')
            f_sub = find_field('subtitle')
            f_date = find_field('published_date') or find_field('post_date') or find_field('create_date')
            
            lines_vals = [
                {'schema_field_path': 'headline', 'source_type': 'odoo_field', 'odoo_field_id': f_name.id, 'field_type': 'char'},
                {'schema_field_path': 'description', 'source_type': 'odoo_field', 'odoo_field_id': f_sub.id, 'field_type': 'text'},
                {'schema_field_path': 'image', 'source_type': 'token', 'token': '{{ blog.image_url }}', 'field_type': 'url'},
                {'schema_field_path': 'datePublished', 'source_type': 'odoo_field', 'odoo_field_id': f_date.id, 'field_type': 'char'},
                {'schema_field_path': 'author.name', 'source_type': 'token', 'token': '{{ blog.author }}', 'field_type': 'char'},
                {'schema_field_path': 'publisher.name', 'source_type': 'token', 'token': '{{ company.name }}', 'field_type': 'char'},
            ]
        else:
            raise ValidationError(f"No sample mapping available for model '{model_name}'.")
            
        if template:
            self.write({
                'schema_template_id': template.id,
                'line_ids': [Command.clear()] + [Command.create(vals) for vals in lines_vals]
            })
        else:
            raise ValidationError("Standard Schema Template not found for this model.")
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sample Loaded',
                'message': f'Successfully loaded sample mapping for {model_name}.',
                'type': 'success',
                'sticky': False,
            }
        }


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
    target_model_id = fields.Many2one('ir.model', related='mapping_id.target_model_id', store=True)
    odoo_field_id = fields.Many2one(
        'ir.model.fields', string='Odoo Field',
        domain="[('model_id', '=', target_model_id)]"
    )
    odoo_field_name = fields.Char(
        string='Odoo Field Technical Name',
        compute='_compute_odoo_field_name', store=True
    )
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

    @api.depends('odoo_field_id')
    def _compute_odoo_field_name(self):
        for rec in self:
            rec.odoo_field_name = rec.odoo_field_id.name if rec.odoo_field_id else ''

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'odoo_field_name' in vals and isinstance(vals['odoo_field_name'], str):
                mapping_id = vals.get('mapping_id')
                if mapping_id:
                    mapping = self.env['midvex.schema.mapping'].browse(mapping_id)
                    model_id = mapping.target_model_id.id
                else:
                    model_id = False
                
                if model_id:
                    self._resolve_field_name(vals, model_id)
                del vals['odoo_field_name']
        return super().create(vals_list)

    @api.model
    def _resolve_field_name(self, vals, model_id):
        field_name = vals.get('odoo_field_name')
        if not field_name or not model_id:
            return
        field_rec = self.env['ir.model.fields'].search([
            ('model_id', '=', model_id),
            ('name', '=', field_name)
        ], limit=1)
        vals['odoo_field_id'] = field_rec.id if field_rec else False

    def write(self, vals):
        if 'odoo_field_name' in vals and isinstance(vals['odoo_field_name'], str):
            for rec in self:
                model_id = rec.target_model_id.id
                if model_id:
                    field_rec = self.env['ir.model.fields'].search([
                        ('model_id', '=', model_id),
                        ('name', '=', vals['odoo_field_name'])
                    ], limit=1)
                    rec.odoo_field_id = field_rec
            del vals['odoo_field_name']
        return super().write(vals)

    @api.onchange('schema_field_path')
    def _onchange_schema_field_path(self):
        for line in self:
            if line.schema_field_path:
                line.field_type = _infer_schema_field_type(line.schema_field_path)
