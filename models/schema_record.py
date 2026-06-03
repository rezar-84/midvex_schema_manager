import json
import re
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from markupsafe import Markup

from .json_utils import _safe_json_dumps, _build_jsonld_script

_logger = logging.getLogger(__name__)

_URL_RE = re.compile(r'^https?://', re.IGNORECASE)
_LANG_RE = re.compile(r'^[a-z]{2,3}([_-][A-Z]{2})?$')

# Matches Odoo language URL prefixes: /en/, /no/, /ko_KR/, /zh_TW/ etc.
# Requires a following slash OR end-of-string so /no-deposit is NOT stripped.
_LANG_PREFIX_RE = re.compile(r'^/[a-z]{2,3}(?:_[A-Z]{2})?(?=/|$)')


def _normalize_path(path):
    """Strip Odoo language prefix from a URL path.

    /tr/about    -> /about
    /ko_KR/page  -> /page
    /en          -> /
    /no-deposit  -> /no-deposit   (unchanged — not a language prefix)
    """
    if not path:
        return path
    match = _LANG_PREFIX_RE.match(path)
    if match:
        tail = path[match.end():]
        return tail or '/'
    return path


class MidvexSchemaRecord(models.Model):
    _name = 'midvex.schema.record'
    _description = 'Midvex Schema Record'
    _rec_name = 'name'
    _order = 'priority desc, name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Name', required=True)
    website_id = fields.Many2one(
        'website', string='Website', ondelete='cascade', index=True,
        default=lambda self: self.env['website'].get_current_website(),
    )
    target_type = fields.Selection([
        ('global', 'Global'),
        ('page', 'Website Page'),
        ('url', 'Custom URL'),
    ], string='Target Type', required=True, default='page')
    website_page_id = fields.Many2one(
        'website.page', string='Website Page', ondelete='set null'
    )
    target_url = fields.Char('Target URL / Path',
                              help='Absolute path, e.g. /about or https://example.com/about')
    lang_code = fields.Char('Language Code', required=True, default='en',
                             help='BCP 47 code, e.g. en, no, de')
    schema_template_id = fields.Many2one(
        'midvex.schema.template', string='Schema Template', ondelete='set null'
    )
    schema_type = fields.Char('Schema Type', required=True,
                               help='e.g. Organization, Product, FAQPage, BreadcrumbList')
    active = fields.Boolean('Active', default=True)
    auto_populate = fields.Boolean('Auto-fill from SEO Metadata', default=False)
    manual_json_enabled = fields.Boolean('Enable Manual JSON Override', default=False)
    manual_json = fields.Text('Manual JSON')
    generated_json = fields.Text('Generated JSON', readonly=True)
    generated_html = fields.Text('Generated HTML', readonly=True)
    validation_status = fields.Selection([
        ('draft', 'Draft'),
        ('valid', 'Valid'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Validation Status', default='draft', readonly=True)
    validation_message = fields.Text('Validation Message', readonly=True)
    duplicate_warning = fields.Char('Duplicate Warning', readonly=True)
    priority = fields.Integer('Priority', default=10,
                               help='Higher value = rendered earlier in <head>')
    last_generated_at = fields.Datetime('Last Generated', readonly=True)

    field_value_ids = fields.One2many(
        'midvex.schema.field.value', 'schema_record_id', string='Field Values'
    )
    faq_item_ids = fields.One2many(
        'midvex.schema.faq.item', 'schema_record_id', string='FAQ Items'
    )
    breadcrumb_item_ids = fields.One2many(
        'midvex.schema.breadcrumb.item', 'schema_record_id', string='Breadcrumb Items'
    )

    # DB-level guard for URL-based records.
    # NULL values are not considered equal by PostgreSQL UNIQUE, so the Python
    # constraint _check_unique_schema_context handles page/global uniqueness.
    _sql_constraints = [
        (
            'unique_url_schema_per_website_lang',
            'UNIQUE(website_id, target_url, lang_code, schema_type)',
            'A schema record with the same website, URL, language and type already exists.',
        ),
    ]

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains('website_id', 'target_type', 'website_page_id', 'target_url',
                    'lang_code', 'schema_type')
    def _check_unique_schema_context(self):
        for rec in self:
            domain = [
                ('id', '!=', rec.id),
                ('active', '=', True),
                ('website_id', '=', rec.website_id.id),
                ('lang_code', '=', rec.lang_code),
                ('schema_type', '=', rec.schema_type),
                ('target_type', '=', rec.target_type),
            ]
            if rec.target_type == 'page' and rec.website_page_id:
                domain.append(('website_page_id', '=', rec.website_page_id.id))
            elif rec.target_type == 'url' and rec.target_url:
                domain.append(('target_url', '=', rec.target_url))

            if self.search_count(domain):
                raise ValidationError(
                    f'A schema record with website "{rec.website_id.name}", '
                    f'language "{rec.lang_code}" and type "{rec.schema_type}" '
                    f'already exists for this target.'
                )

    @api.constrains('manual_json')
    def _check_manual_json(self):
        for rec in self:
            if rec.manual_json_enabled and rec.manual_json:
                try:
                    json.loads(rec.manual_json)
                except (json.JSONDecodeError, TypeError):
                    raise ValidationError('Manual JSON must be valid JSON.')

    # ------------------------------------------------------------------
    # Pure schema data builders (NO database writes)
    # ------------------------------------------------------------------

    def _build_json_from_fields(self, lang_code=None):
        self.ensure_one()
        data = {}
        if self.schema_template_id:
            data = self.schema_template_id.get_default_structure()

        values = self.field_value_ids
        if lang_code:
            values = values.filtered(
                lambda v: not v.lang_code or v.lang_code == lang_code
            )
        for fv in values.sorted('sequence'):
            val = fv.get_value()
            if val is not None and val != '' and val is not False:
                data[fv.field_key] = val

        return data

    def _build_faqpage_json(self, lang_code=None):
        self.ensure_one()
        items = self.faq_item_ids.filtered(lambda f: f.active)
        if lang_code:
            items = items.filtered(lambda f: not f.lang_code or f.lang_code == lang_code)
        items = items.sorted('position')
        return {
            '@context': 'https://schema.org',
            '@type': 'FAQPage',
            'mainEntity': [
                {
                    '@type': 'Question',
                    'name': item.question,
                    'acceptedAnswer': {
                        '@type': 'Answer',
                        'text': item.answer,
                    },
                }
                for item in items
            ],
        }

    def _build_breadcrumb_json(self, lang_code=None):
        self.ensure_one()
        items = self.breadcrumb_item_ids
        if lang_code:
            items = items.filtered(lambda b: not b.lang_code or b.lang_code == lang_code)
        items = items.sorted('position')
        return {
            '@context': 'https://schema.org',
            '@type': 'BreadcrumbList',
            'itemListElement': [
                {
                    '@type': 'ListItem',
                    'position': item.position,
                    'name': item.name,
                    'item': item.url,
                }
                for item in items
            ],
        }

    def build_schema_data(self):
        """
        Return the schema data dict for this record WITHOUT any database write.

        This is the safe read-only path used during public website rendering.
        Backend methods (generate_json, render_html) call this internally too.
        """
        self.ensure_one()
        if self.manual_json_enabled and self.manual_json:
            try:
                # Re-parse: ensures no raw string injection escapes json.loads
                return json.loads(self.manual_json)
            except (json.JSONDecodeError, TypeError):
                return None
        if self.schema_type == 'FAQPage':
            return self._build_faqpage_json(self.lang_code)
        if self.schema_type == 'BreadcrumbList':
            return self._build_breadcrumb_json(self.lang_code)
        data = self._build_json_from_fields(self.lang_code)
        data.setdefault('@context', 'https://schema.org')
        data.setdefault('@type', self.schema_type)
        return data

    # ------------------------------------------------------------------
    # Backend methods — may write to database (for caching / preview)
    # ------------------------------------------------------------------

    def generate_json(self):
        """
        Backend: compute schema data, store in generated_json + update last_generated_at.
        Do NOT call this during public page rendering.
        """
        self.ensure_one()
        data = self.build_schema_data()
        if data is None:
            self.write({
                'validation_status': 'error',
                'validation_message': 'Manual JSON is not valid JSON.',
            })
            return None
        result = json.dumps(data, ensure_ascii=False, indent=2)
        self.write({
            'generated_json': result,
            'last_generated_at': fields.Datetime.now(),
        })
        return data

    def validate_schema(self):
        """Backend: run validation checks and write validation_status + validation_message."""
        self.ensure_one()
        errors = []
        warnings = []

        data = self.build_schema_data()

        if not isinstance(data, dict):
            errors.append('Schema must be a JSON object.')
        else:
            if '@context' not in data:
                errors.append('Missing required @context.')
            if '@type' not in data:
                errors.append('Missing required @type.')

            if self.lang_code and not _LANG_RE.match(self.lang_code):
                warnings.append(
                    f'Language code "{self.lang_code}" may not be a valid BCP 47 code.'
                )

            for fv in self.field_value_ids.filtered(lambda v: v.field_type == 'url'):
                val = fv.value_url
                if val and not _URL_RE.match(val):
                    warnings.append(
                        f'Field "{fv.field_key}": URL does not start with http(s)://.'
                    )

            if self.schema_type == 'Product':
                # Check both stored field keys AND the built data for non-empty values
                field_keys = set(
                    fv.field_key
                    for fv in self.field_value_ids
                    if fv.get_value() not in (None, '', False)
                ) | (set(data.keys()) - {'@context', '@type'})
                missing = {'name', 'description', 'image'} - field_keys
                if missing:
                    errors.append(
                        f'Product schema requires: {", ".join(sorted(missing))}.'
                    )

            elif self.schema_type == 'FAQPage':
                if not self.faq_item_ids.filtered(lambda f: f.active):
                    errors.append('FAQPage schema requires at least one active FAQ item.')

            elif self.schema_type == 'BreadcrumbList':
                if not self.breadcrumb_item_ids:
                    errors.append('BreadcrumbList schema requires at least one breadcrumb item.')
                else:
                    positions = sorted(self.breadcrumb_item_ids.mapped('position'))
                    if positions != list(range(1, len(positions) + 1)):
                        warnings.append(
                            'BreadcrumbList item positions should be sequential starting from 1.'
                        )

        dup = self.check_duplicate_schema()
        if dup:
            warnings.append(dup)

        if errors:
            status, message = 'error', '\n'.join(errors + warnings)
        elif warnings:
            status, message = 'warning', '\n'.join(warnings)
        else:
            status, message = 'valid', 'Schema is valid.'

        self.write({'validation_status': status, 'validation_message': message})
        return status

    def render_html(self):
        """
        Backend: build a safe script tag and cache it in generated_html.
        Uses _build_jsonld_script for XSS-safe output.
        Do NOT call this during public page rendering — use build_schema_data() instead.
        """
        self.ensure_one()
        data = self.build_schema_data()
        if not data:
            return ''
        script = _build_jsonld_script(data)
        self.write({'generated_html': script})
        return script

    # ------------------------------------------------------------------
    # Button / action methods
    # ------------------------------------------------------------------

    def action_validate(self):
        self.ensure_one()
        self.generate_json()
        self.validate_schema()
        return True

    def action_generate_json(self):
        self.ensure_one()
        self.generate_json()
        return True

    def action_open_rich_results_test(self):
        self.ensure_one()
        url = self.target_url or ''
        if url and not _URL_RE.match(url):
            domain = ''
            if self.website_id and self.website_id.domain:
                domain = self.website_id.domain.rstrip('/')
            url = domain + url
        test_url = 'https://search.google.com/test/rich-results'
        if url:
            test_url += '?url=' + url
        return {
            'type': 'ir.actions.act_url',
            'url': test_url,
            'target': 'new',
        }

    def action_open_lang_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create for All Languages',
            'res_model': 'midvex.schema.lang.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_schema_record_id': self.id},
        }

    def action_auto_populate(self):
        self.ensure_one()
        page = self.website_page_id
        if not page:
            return False

        view = page.view_id
        meta_title = (view.name or '') if view else ''
        meta_description = ''
        if view:
            meta_description = getattr(view, 'website_meta_description', '') or ''

        candidates = {
            'name': meta_title,
            'description': meta_description,
            'url': self.target_url or '',
            'inLanguage': self.lang_code,
        }

        if self.schema_template_id:
            for schema_field, odoo_key in self.schema_template_id.get_auto_mapping().items():
                if odoo_key in candidates and candidates[odoo_key]:
                    candidates[schema_field] = candidates[odoo_key]

        for field_key, value in candidates.items():
            if not value:
                continue
            field_type = 'url' if field_key in ('url', 'image') else 'char'
            existing = self.field_value_ids.filtered(lambda v: v.field_key == field_key)
            if existing:
                existing[0].write(
                    {'value_url': value} if field_type == 'url' else {'value_char': value}
                )
            else:
                self.env['midvex.schema.field.value'].create({
                    'schema_record_id': self.id,
                    'field_key': field_key,
                    'field_label': field_key.replace('_', ' ').title(),
                    'field_type': field_type,
                    'value_char': value if field_type == 'char' else False,
                    'value_url': value if field_type == 'url' else False,
                    'lang_code': self.lang_code,
                })
        return True

    # ------------------------------------------------------------------
    # Frontend rendering (MUST remain read-only — no write() calls)
    # ------------------------------------------------------------------

    @api.model
    def render_schema_for_request(self, request):
        """
        Called from the website.layout QWeb template on every public page view.

        Contract:
        - MUST NOT write to any database record.
        - Returns Markup (safe HTML) of all applicable <script> tags.
        - Global Settings Organization/WebSite schema is rendered first.
        - Page/URL-specific records follow, sorted by priority desc.
        """
        try:
            website = getattr(request, 'website', None)
            if not website:
                website = request.env['website'].get_current_website()

            lang = getattr(request, 'lang', None)
            if lang and hasattr(lang, 'code'):
                lang_code = lang.code.split('_')[0]
            else:
                lang_code = 'en'

            raw_path = (
                getattr(request.httprequest, 'path', '')
                if hasattr(request, 'httprequest')
                else ''
            )
            current_path = _normalize_path(raw_path)
        except Exception as exc:
            _logger.warning('midvex_schema_manager: could not resolve request context: %s', exc)
            return Markup('')

        parts = []

        # ── 1. Global Settings: Organization + WebSite schema ─────────
        try:
            settings_parts = (
                self.env['midvex.schema.settings']
                .sudo()
                ._render_global_for_website(website, lang_code)
            )
            parts.extend(settings_parts)
        except Exception as exc:
            _logger.error(
                'midvex_schema_manager: error rendering global settings schema: %s', exc
            )

        # ── 2. Schema records (global target_type + page + url) ────────
        base_domain = [
            ('active', '=', True),
            ('website_id', '=', website.id),
            ('lang_code', '=', lang_code),
        ]

        global_records = self.sudo().search(
            base_domain + [('target_type', '=', 'global')]
        )

        matching_pages = self.env['website.page'].sudo().search(
            [('url', '=', current_path)]
        )
        page_records = self.sudo().search(
            base_domain + [
                ('target_type', '=', 'page'),
                ('website_page_id', 'in', matching_pages.ids),
            ]
        )

        url_records = self.sudo().search(
            base_domain + [
                ('target_type', '=', 'url'),
                ('target_url', '=', current_path),
            ]
        )

        all_records = (global_records + page_records + url_records).sorted(
            'priority', reverse=True
        )

        for record in all_records:
            try:
                data = record.build_schema_data()
                if data:
                    parts.append(_build_jsonld_script(data))
            except Exception as exc:
                _logger.error(
                    'midvex_schema_manager: error rendering schema record %s: %s',
                    record.id, exc,
                )

        return Markup('\n'.join(parts))

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    @api.model
    def suggest_breadcrumbs_from_url(self, url):
        if not url:
            return []
        path = url.split('?')[0].rstrip('/')
        parts = [p for p in path.split('/') if p]
        crumbs = [{'name': 'Home', 'url': '/'}]
        accumulated = ''
        for part in parts:
            accumulated += '/' + part
            name = part.replace('-', ' ').replace('_', ' ').title()
            crumbs.append({'name': name, 'url': accumulated})
        return crumbs

    def check_duplicate_schema(self):
        self.ensure_one()
        domain = [
            ('id', '!=', self.id or 0),
            ('active', '=', True),
            ('website_id', '=', self.website_id.id),
            ('lang_code', '=', self.lang_code),
            ('schema_type', '=', self.schema_type),
        ]
        if self.target_type == 'page' and self.website_page_id:
            domain.append(('website_page_id', '=', self.website_page_id.id))
        elif self.target_type == 'url' and self.target_url:
            domain.append(('target_url', '=', self.target_url))
        elif self.target_type == 'global':
            domain.append(('target_type', '=', 'global'))

        duplicates = self.search(domain)
        if duplicates:
            names = ', '.join(duplicates.mapped('name'))
            return f'Possible duplicate schema found: {names}'
        return ''

    @api.onchange('schema_template_id')
    def _onchange_schema_template_id(self):
        if not self.schema_template_id:
            return
        self.schema_type = self.schema_template_id.schema_type
        self.field_value_ids = [(5, 0, 0)]
        required_fields = self.schema_template_id.get_required_fields()
        new_lines = []
        for field_key in required_fields:
            field_type = 'url' if field_key in ('url', 'image', 'logo') else 'char'
            new_lines.append((0, 0, {
                'field_key': field_key,
                'field_label': field_key.replace('_', ' ').title(),
                'field_type': field_type,
                'required': True,
            }))
        self.field_value_ids = new_lines

    @api.model
    def regenerate_all_active_schemas(self):
        """Scheduled action: rebuild generated_json + generated_html for all active records."""
        records = self.search([('active', '=', True)])
        for record in records:
            try:
                record.generate_json()
                record.render_html()
            except Exception as exc:
                _logger.error(
                    'midvex_schema_manager: error regenerating schema %s: %s',
                    record.id, exc,
                )
        return True

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            warning = record.check_duplicate_schema()
            if warning:
                super(MidvexSchemaRecord, record).write({'duplicate_warning': warning})
        return records

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get('_midvex_skip_dup_check'):
            return result
        trigger_fields = {
            'website_id', 'target_type', 'website_page_id', 'target_url',
            'lang_code', 'schema_type', 'active',
        }
        if trigger_fields & set(vals.keys()):
            for record in self:
                warning = record.check_duplicate_schema()
                super(MidvexSchemaRecord, record).with_context(
                    _midvex_skip_dup_check=True
                ).write({'duplicate_warning': warning})
        return result
