from odoo import fields, models

from .schema_record import _get_schema_lang_code


class MidvexSchemaBatchWizard(models.TransientModel):
    _name = 'midvex.schema.batch.wizard'
    _description = 'Structured Data Batch Operations'

    website_id = fields.Many2one(
        'website', string='Website',
        default=lambda self: self.env['website'].get_current_website(),
    )
    operation = fields.Selection([
        ('validate', 'Validate all active schemas'),
        ('regenerate', 'Generate previews for all active schemas'),
        ('translations', 'Create translations for website languages'),
    ], string='Operation', required=True, default='validate')

    def _schema_exists_for_lang(self, source, lang_code):
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
        return bool(
            self.env['midvex.schema.record'].with_context(active_test=False).search_count(domain)
        )

    def action_run(self):
        self.ensure_one()
        domain = [('active', '=', True)]
        if self.website_id:
            domain.append(('website_id', '=', self.website_id.id))
        records = self.env['midvex.schema.record'].search(domain)
        if self.operation == 'validate':
            for record in records:
                record.validate_schema()
            message = '%s active schema records validated.' % len(records)
        elif self.operation == 'regenerate':
            for record in records:
                record.generate_json()
                record.render_html()
            message = '%s active schema previews regenerated.' % len(records)
        else:
            created = 0
            skipped = 0
            languages = self.website_id.language_ids if self.website_id else self.env['res.lang'].search([('active', '=', True)])
            for record in records:
                if not record.lang_code:
                    skipped += len(languages)
                    continue
                for lang in languages:
                    lang_code = _get_schema_lang_code(lang.code)
                    if lang_code == record.lang_code or self._schema_exists_for_lang(record, lang_code):
                        skipped += 1
                        continue
                    new_record = record.copy({
                        'lang_code': lang_code,
                        'name': '%s [%s]' % (record.name, lang_code),
                        'generated_json': False,
                        'generated_html': False,
                        'validation_status': 'draft',
                        'validation_message': False,
                        'last_generated_at': False,
                        'duplicate_warning': False,
                    })
                    new_record.field_value_ids.write({'lang_code': False})
                    new_record.faq_item_ids.write({'lang_code': False})
                    new_record.breadcrumb_item_ids.write({'lang_code': False})
                    created += 1
            message = '%s translated schema records created, %s skipped.' % (created, skipped)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Batch operation complete',
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }
