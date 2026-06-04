from urllib.parse import urlparse

from odoo import api, fields, models

from .schema_record import _strip_language_prefix, _get_active_language_url_codes, _get_schema_lang_code


class MidvexSchemaPageWizard(models.TransientModel):
    _name = 'midvex.schema.page.wizard'
    _description = 'Create Page Schema Wizard'

    website_id = fields.Many2one(
        'website', string='Website', required=True,
        default=lambda self: self.env['website'].get_current_website(),
    )
    target_url = fields.Char(
        'Current / Target URL',
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

    @api.model
    def _is_backend_request_path(self, path):
        if not path:
            return False
        backend_prefixes = (
            '/web',
            '/mail',
            '/bus',
            '/longpolling',
            '/websocket',
            '/report',
        )
        return path == '/web' or any(path.startswith(prefix + '/') for prefix in backend_prefixes)

    @api.model
    def _get_request_candidate_url(self):
        """Return a frontend URL/path from the active request, never an RPC path."""
        try:
            from odoo.http import request
            request_path = getattr(request.httprequest, 'path', '') or ''
            if request_path and not self._is_backend_request_path(request_path):
                return request_path

            referrer = getattr(request.httprequest, 'referrer', '') or ''
            if referrer:
                ref_path = urlparse(referrer).path or ''
                if ref_path and not self._is_backend_request_path(ref_path):
                    return referrer
        except Exception:
            return ''
        return ''

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        website = self.env['website'].browse(vals.get('website_id')) if vals.get('website_id') else self.env['website'].get_current_website()
        context = self.env.context
        raw_url = (
            context.get('current_url') or
            context.get('target_url') or
            context.get('active_url') or
            context.get('default_target_url') or
            ''
        )
        if not raw_url:
            raw_url = self._get_request_candidate_url()
            try:
                from odoo.http import request
                if getattr(request, 'lang', None) and request.lang.code:
                    vals.setdefault('lang_code', _get_schema_lang_code(request.lang.code))
            except Exception:
                pass
        if raw_url:
            path = urlparse(raw_url).path if raw_url.startswith('http') else raw_url
            path = path or '/'
            vals.setdefault('target_url', path)
            active_lang_codes = _get_active_language_url_codes(website)
            normalized = _strip_language_prefix(path, active_lang_codes)
            page_domain = [('url', 'in', list({path, normalized} - {''}))]
            if 'website_id' in self.env['website.page']._fields:
                page_domain.append(('website_id', 'in', [False, website.id]))
            page = self.env['website.page'].search(page_domain, limit=1)
            if page:
                vals.setdefault('website_page_id', page.id)
                vals.setdefault('target_type', 'page')
            else:
                vals.setdefault('target_type', 'url')
        vals.setdefault('website_id', website.id)
        vals.setdefault('lang_code', _get_schema_lang_code(self.env.lang))
        return vals

    @api.onchange('schema_template_id')
    def _onchange_schema_template_id(self):
        if self.schema_template_id:
            self.target_type = self.schema_template_id.get_recommended_target_type()

    @api.onchange('website_page_id')
    def _onchange_website_page_id(self):
        if self.website_page_id:
            self.target_type = 'page'
            self.target_url = self.website_page_id.url

    @api.onchange('target_url', 'website_id')
    def _onchange_target_url(self):
        if not self.target_url or not self.website_id:
            return
        path = urlparse(self.target_url).path if self.target_url.startswith('http') else self.target_url
        active_lang_codes = _get_active_language_url_codes(self.website_id)
        normalized = _strip_language_prefix(path, active_lang_codes)
        page_domain = [('url', 'in', list({path, normalized} - {''}))]
        if 'website_id' in self.env['website.page']._fields:
            page_domain.append(('website_id', 'in', [False, self.website_id.id]))
        page = self.env['website.page'].search(page_domain, limit=1)
        if page:
            self.website_page_id = page
            self.target_type = 'page'

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
