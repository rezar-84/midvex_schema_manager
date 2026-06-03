from odoo import api, fields, models


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
            active_langs = self.env['res.lang'].search([('active', '=', True)])
            vals['language_ids'] = [(6, 0, active_langs.ids)]
        return vals

    def action_create_for_languages(self):
        self.ensure_one()
        source = self.schema_record_id
        for lang in self.language_ids:
            # Normalise 'en_US' → 'en', 'ko_KR' → 'ko'
            lang_code = lang.code.split('_')[0]
            if lang_code == source.lang_code:
                continue

            # Skip if a record already exists for this lang + target combination
            domain = [
                ('website_id', '=', source.website_id.id),
                ('target_type', '=', source.target_type),
                ('schema_type', '=', source.schema_type),
                ('lang_code', '=', lang_code),
                ('id', '!=', source.id),
            ]
            if source.target_type == 'page' and source.website_page_id:
                domain.append(('website_page_id', '=', source.website_page_id.id))
            elif source.target_type == 'url' and source.target_url:
                domain.append(('target_url', '=', source.target_url))
            if self.env['midvex.schema.record'].search_count(domain):
                continue

            new_record = source.copy({
                'lang_code': lang_code,
                'name': '{} [{}]'.format(source.name, lang_code),
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
            if new_record.field_value_ids:
                new_record.field_value_ids.write({'lang_code': False})
            if new_record.faq_item_ids:
                new_record.faq_item_ids.write({'lang_code': False})
            if new_record.breadcrumb_item_ids:
                new_record.breadcrumb_item_ids.write({'lang_code': False})

        return {'type': 'ir.actions.act_window_close'}
