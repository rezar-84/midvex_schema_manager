from odoo import api, fields, models


class MidvexSchemaPageWizard(models.TransientModel):
    _name = 'midvex.schema.page.wizard'
    _description = 'Create Page Schema Wizard'

    website_id = fields.Many2one(
        'website', string='Website', required=True,
        default=lambda self: self.env['website'].get_current_website(),
    )
    target_url = fields.Char(
        'Current / Target URL', required=True,
        help='Use /page-url, /tr/page-url, or a full https://example.com/page-url URL.'
    )
    website_page_id = fields.Many2one('website.page', string='Website Page')
    lang_code = fields.Char('Language Code', required=True, default='en')
    schema_template_id = fields.Many2one(
        'midvex.schema.template', string='Schema Template', required=True
    )
    auto_populate = fields.Boolean('Auto-fill from page SEO metadata', default=True)

    @api.onchange('website_page_id')
    def _onchange_website_page_id(self):
        if self.website_page_id:
            self.target_url = self.website_page_id.url

    def action_create_schema(self):
        self.ensure_one()
        record = self.env['midvex.schema.record'].create({
            'name': '%s schema for %s' % (
                self.schema_template_id.name,
                self.website_page_id.display_name or self.target_url,
            ),
            'website_id': self.website_id.id,
            'target_type': 'page' if self.website_page_id else 'url',
            'website_page_id': self.website_page_id.id,
            'target_url': self.target_url,
            'lang_code': self.lang_code,
            'schema_template_id': self.schema_template_id.id,
            'auto_populate': self.auto_populate,
        })
        if self.auto_populate and record.website_page_id:
            record.action_auto_populate()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Page Schema',
            'res_model': 'midvex.schema.record',
            'view_mode': 'form',
            'res_id': record.id,
            'target': 'current',
        }
