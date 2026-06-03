from odoo import fields, models


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
    ], string='Operation', required=True, default='validate')

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
        else:
            for record in records:
                record.generate_json()
                record.render_html()
            message = '%s active schema previews regenerated.' % len(records)
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
