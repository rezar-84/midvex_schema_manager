from odoo import fields, models, tools


class MidvexSchemaCoverageReport(models.Model):
    _name = 'midvex.schema.coverage.report'
    _description = 'Structured Data Coverage Report'
    _auto = False
    _order = 'url'

    website_page_id = fields.Many2one('website.page', string='Website Page', readonly=True)
    schema_record_id = fields.Many2one('midvex.schema.record', string='Schema Record', readonly=True)
    website_id = fields.Many2one('website', string='Website', readonly=True)
    target_type = fields.Selection([
        ('page', 'Website Page'),
        ('url', 'Custom URL'),
    ], readonly=True)
    url = fields.Char(readonly=True)
    schema_types = fields.Char('Schema Types', readonly=True)
    validation_status = fields.Selection([
        ('missing', 'Missing Schema'),
        ('draft', 'Draft'),
        ('valid', 'Valid'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], readonly=True)
    needs_attention = fields.Boolean(readonly=True)
    page_published = fields.Boolean('Page Published', readonly=True)
    page_create_date = fields.Datetime('Page Created On', readonly=True)
    page_write_date = fields.Datetime('Page Last Modified', readonly=True)
    page_create_uid = fields.Many2one('res.users', string='Page Created By', readonly=True)
    page_write_uid = fields.Many2one('res.users', string='Page Last Modified By', readonly=True)

    def action_open_website_page(self):
        self.ensure_one()
        if not self.website_page_id:
            return self.action_open_website_url()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Website Page',
            'res_model': 'website.page',
            'view_mode': 'form',
            'res_id': self.website_page_id.id,
            'target': 'current',
        }

    def action_open_website_url(self):
        self.ensure_one()
        if not self.url:
            return False
        if self.url.startswith('http'):
            url = self.url
        else:
            domain = (getattr(self.website_id, 'domain', '') or '').strip()
            base = domain.rstrip('/') if domain.startswith('http') else ('https://' + domain.rstrip('/') if domain else '')
            url = base + self.url if base else self.url
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_open_page_schemas(self):
        self.ensure_one()
        schema_domain = [
            ('website_id', '=', self.website_id.id),
            ('target_type', '=', self.target_type),
        ]
        if self.target_type == 'page':
            schema_domain.append(('website_page_id', '=', self.website_page_id.id))
        else:
            schema_domain.append(('target_url', '=', self.url))
        records = self.env['midvex.schema.record'].search(schema_domain)
        if len(records) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Page Schema',
                'res_model': 'midvex.schema.record',
                'view_mode': 'form',
                'res_id': records.id,
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Page Schemas',
            'res_model': 'midvex.schema.record',
            'view_mode': 'list,form',
            'domain': schema_domain,
            'context': {
                'default_target_type': self.target_type,
                'default_website_page_id': self.website_page_id.id if self.website_page_id else False,
                'default_website_id': self.website_id.id,
                'default_target_url': self.url,
            },
        }

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        page_fields = self.env['website.page']._fields
        if 'is_published' in page_fields:
            published_expr = 'COALESCE(p.is_published, false)'
            published_group = ', p.is_published'
        elif 'website_published' in page_fields:
            published_expr = 'COALESCE(p.website_published, false)'
            published_group = ', p.website_published'
        else:
            published_expr = 'false'
            published_group = ''
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    p.id AS id,
                    p.id AS website_page_id,
                    NULL::integer AS schema_record_id,
                    p.website_id AS website_id,
                    'page'::varchar AS target_type,
                    p.url AS url,
                    COALESCE(string_agg(DISTINCT r.schema_type, ', '), '') AS schema_types,
                    CASE
                        WHEN COUNT(r.id) = 0 THEN 'missing'
                        WHEN bool_or(r.validation_status = 'error') THEN 'error'
                        WHEN bool_or(r.validation_status = 'warning') THEN 'warning'
                        WHEN bool_or(r.validation_status = 'draft') THEN 'draft'
                        ELSE 'valid'
                    END AS validation_status,
                    CASE
                        WHEN COUNT(r.id) = 0 THEN true
                        WHEN bool_or(r.validation_status IN ('error', 'warning', 'draft')) THEN true
                        ELSE false
                    END AS needs_attention,
                    %s AS page_published,
                    p.create_date AS page_create_date,
                    p.write_date AS page_write_date,
                    p.create_uid AS page_create_uid,
                    p.write_uid AS page_write_uid
                FROM website_page p
                LEFT JOIN midvex_schema_record r
                    ON r.website_page_id = p.id
                    AND r.target_type = 'page'
                    AND r.active = true
                GROUP BY p.id, p.website_id, p.url%s, p.create_date, p.write_date, p.create_uid, p.write_uid
                UNION ALL
                SELECT
                    -MIN(r.id) AS id,
                    NULL::integer AS website_page_id,
                    MIN(r.id) AS schema_record_id,
                    r.website_id AS website_id,
                    'url'::varchar AS target_type,
                    r.target_url AS url,
                    COALESCE(string_agg(DISTINCT r.schema_type, ', '), '') AS schema_types,
                    CASE
                        WHEN bool_or(r.validation_status = 'error') THEN 'error'
                        WHEN bool_or(r.validation_status = 'warning') THEN 'warning'
                        WHEN bool_or(r.validation_status = 'draft') THEN 'draft'
                        ELSE 'valid'
                    END AS validation_status,
                    CASE
                        WHEN bool_or(r.validation_status IN ('error', 'warning', 'draft')) THEN true
                        ELSE false
                    END AS needs_attention,
                    false AS page_published,
                    NULL::timestamp AS page_create_date,
                    MAX(r.write_date) AS page_write_date,
                    NULL::integer AS page_create_uid,
                    NULL::integer AS page_write_uid
                FROM midvex_schema_record r
                WHERE r.target_type = 'url'
                    AND r.active = true
                    AND COALESCE(r.target_url, '') != ''
                GROUP BY r.website_id, r.target_url
            )
        """ % (self._table, published_expr, published_group))
