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
    target_type = fields.Selection([
        ('global', 'Global'),
        ('page', 'Website Page'),
        ('url', 'Custom URL'),
    ], string='Target Type', required=True, default='page')
    lang_code = fields.Char('Language Code', required=True, default='en')
    schema_template_id = fields.Many2one(
        'midvex.schema.template', string='Schema Template', required=True
    )
    add_optional_fields = fields.Boolean('Add optional fields')
    auto_populate = fields.Boolean('Auto-fill from page SEO metadata', default=True)

    @api.onchange('schema_template_id')
    def _onchange_schema_template_id(self):
        if self.schema_template_id:
            self.target_type = self.schema_template_id.get_recommended_target_type()

    @api.onchange('website_page_id')
    def _onchange_website_page_id(self):
        if self.website_page_id:
            self.target_type = 'page'
            self.target_url = self.website_page_id.url

    def action_create_schema(self):
        self.ensure_one()
        target_type = self.target_type
        if target_type == 'page' and not self.website_page_id:
            target_type = 'url'
        record = self.env['midvex.schema.record'].create({
            'name': '%s schema for %s' % (
                self.schema_template_id.name,
                self.website_page_id.display_name or self.target_url or self.website_id.name,
            ),
            'website_id': self.website_id.id,
            'target_type': target_type,
            'website_page_id': self.website_page_id.id,
            'target_url': self.target_url if target_type != 'global' else False,
            'lang_code': self.lang_code,
            'schema_template_id': self.schema_template_id.id,
            'auto_populate': self.auto_populate,
        })
        if self.add_optional_fields:
            record.action_add_optional_fields()
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
