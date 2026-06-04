from odoo import fields, models, tools


class MidvexSchemaCoverageReport(models.Model):
    _name = 'midvex.schema.coverage.report'
    _description = 'Structured Data Coverage Report'
    _auto = False
    _order = 'url'

    website_page_id = fields.Many2one('website.page', string='Website Page', readonly=True)
    website_id = fields.Many2one('website', string='Website', readonly=True)
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

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    p.id AS id,
                    p.id AS website_page_id,
                    p.website_id AS website_id,
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
                    END AS needs_attention
                FROM website_page p
                LEFT JOIN midvex_schema_record r
                    ON r.website_page_id = p.id
                    AND r.target_type = 'page'
                    AND r.active = true
                GROUP BY p.id, p.website_id, p.url
            )
        """ % self._table)
