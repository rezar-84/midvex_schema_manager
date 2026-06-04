from odoo import api, fields, models, Command
from odoo.exceptions import UserError


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
            source_id = self.env.context.get('default_schema_record_id')
            langs = self.env['res.lang']
            if source_id:
                source = self.env['midvex.schema.record'].browse(source_id)
                if source.exists() and source.website_id:
                    langs = source.website_id.language_ids
            if not langs:
                langs = self.env['res.lang'].search([('active', '=', True)])
            vals['language_ids'] = [Command.set(langs.ids)]
        return vals

    def action_create_for_languages(self):
        self.ensure_one()
        if not self.language_ids:
            raise UserError('Please select at least one language.')

        source = self.schema_record_id

        # Accumulate records to update in batch after the loop (performance optimization)
        fields_to_update = self.env['midvex.schema.field.value']
        faqs_to_update = self.env['midvex.schema.faq.item']
        breadcrumbs_to_update = self.env['midvex.schema.breadcrumb.item']

        created_count = 0
        for lang in self.language_ids:
            # Normalise and lowercase 'en_US' → 'en', 'ko_KR' → 'ko'
            lang_code = lang.code.split('_')[0].lower()
            if lang_code == source.lang_code:
                continue

            # Skip if a record already exists for this lang + target combination
            # Use active_test=False to include archived records to prevent database constraint failures
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
            created_count += 1

            # Accumulate child records for batch updates
            fields_to_update |= new_record.field_value_ids
            faqs_to_update |= new_record.faq_item_ids
            breadcrumbs_to_update |= new_record.breadcrumb_item_ids

        # Write updates in batch instead of loop iteration (O(1) queries instead of O(N))
        if fields_to_update:
            fields_to_update.write({'lang_code': False})
        if faqs_to_update:
            faqs_to_update.write({'lang_code': False})
        if breadcrumbs_to_update:
            breadcrumbs_to_update.write({'lang_code': False})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Create Language Copies',
                'message': f'Successfully created {created_count} language copy/copies.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

