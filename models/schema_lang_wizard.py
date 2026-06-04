from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from .schema_record import _get_schema_lang_code


class MidvexSchemaLangWizard(models.TransientModel):
    _name = 'midvex.schema.lang.wizard'
    _description = 'Create Schema Records for Multiple Languages'

    schema_record_id = fields.Many2one(
        'midvex.schema.record', string='Source Schema Record',
        required=True, ondelete='cascade',
    )
    language_ids = fields.Many2many(
        'res.lang', string='Languages',
        domain="[('active', '=', True)]",
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'language_ids' in fields_list:
            source = self.env['midvex.schema.record'].browse(
                vals.get('schema_record_id') or self.env.context.get('default_schema_record_id')
            )
            active_langs = source.website_id.language_ids if source and source.website_id else self.env['res.lang']
            if not active_langs:
                active_langs = self.env['res.lang'].search([('active', '=', True)])
            vals['language_ids'] = [Command.set(active_langs.ids)]
        return vals

    def action_create_for_languages(self):
        self.ensure_one()
        if not self.language_ids:
            raise UserError('Select at least one website language.')
        source = self.schema_record_id
        created_count = 0
        skipped_count = 0
        field_values = self.env['midvex.schema.field.value']
        faq_items = self.env['midvex.schema.faq.item']
        breadcrumb_items = self.env['midvex.schema.breadcrumb.item']
        for lang in self.language_ids:
            # Normalise 'en_US' -> 'en', 'ko_KR' -> 'ko'
            lang_code = _get_schema_lang_code(lang.code)
            if lang_code == source.lang_code:
                skipped_count += 1
                continue

            # Skip if a record already exists for this lang + target combination
            domain = [
                ('website_id', '=', source.website_id.id),
                ('target_type', '=', source.target_type),
                ('schema_type', '=', source.schema_type),
                ('lang_code', '=', lang_code),
                ('id', '!=', source.id),
            ]
            if source.target_type == 'page':
                domain.append(('website_page_id', '=', source.website_page_id.id))
            elif source.target_type == 'url':
                domain.append(('target_url', '=', source.target_url))
            if self.env['midvex.schema.record'].with_context(active_test=False).search_count(domain):
                skipped_count += 1
                continue

            new_record = source.copy({
                'lang_code': lang_code,
                'name': f'{source.name} [{lang_code}]',
                'generated_json': False,
                'generated_html': False,
                'validation_status': 'draft',
                'validation_message': False,
                'last_generated_at': False,
                'duplicate_warning': False,
            })

            # MVP: language lives on the parent record only.
            # Clear child lang_code so all rows are always included during
            # schema generation, regardless of the language filter.
            field_values |= new_record.field_value_ids
            faq_items |= new_record.faq_item_ids
            breadcrumb_items |= new_record.breadcrumb_item_ids
            created_count += 1

        if field_values:
            field_values.write({'lang_code': False})
        if faq_items:
            faq_items.write({'lang_code': False})
        if breadcrumb_items:
            breadcrumb_items.write({'lang_code': False})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Language schemas created',
                'message': '%s created, %s skipped.' % (created_count, skipped_count),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
