import json
import re
import logging

from odoo import api, fields, models, Command
from odoo.exceptions import ValidationError
from markupsafe import Markup

from .json_utils import _safe_json_dumps, _build_jsonld_script

_logger = logging.getLogger(__name__)

_URL_RE = re.compile(r'^https?://', re.IGNORECASE)
_LANG_RE = re.compile(r'^[a-z]{2,3}([_-][A-Z]{2})?$')

# Fallback regex for language prefixes when website language list is unavailable.
# Requires a trailing slash OR end-of-string so /no-deposit is NOT stripped.
_LANG_PREFIX_RE = re.compile(r'^/[a-z]{2,3}(?:_[A-Z]{2})?(?=/|$)')


# ---------------------------------------------------------------------------
# P4 — Multilingual URL helpers
# ---------------------------------------------------------------------------

def _get_schema_lang_code(odoo_lang_code):
    """Map an Odoo locale code to a 2-letter schema lang code.

    'en_US' → 'en',  'ko_KR' → 'ko',  'tr_TR' → 'tr',  '' → 'en'
    """
    if not odoo_lang_code:
        return 'en'
    return odoo_lang_code.split('_')[0].lower()


def _get_active_language_url_codes(website):
    """Return a set of all language URL codes active on *website*.

    Includes both the Odoo url_code (e.g. 'ko_KR') and the 2-letter prefix
    ('ko') so that either format can match a URL segment.
    Returns an empty set on error so callers fall back to regex stripping.
    """
    codes = set()
    try:
        for lang in website.language_ids:
            url_code = (getattr(lang, 'url_code', '') or '').strip().lower()
            if url_code:
                codes.add(url_code)
            codes.add(lang.code.split('_')[0].lower())
    except Exception:
        pass
    return codes


def _strip_language_prefix(path, active_lang_codes):
    """Strip Odoo language URL prefix from *path*.

    Uses *active_lang_codes* (from the current website) when available,
    otherwise falls back to the regex pattern.

    /tr/about    → /about
    /ko_KR/page  → /page
    /no-deposit  → /no-deposit   (not a language prefix)
    """
    if not path or path == '/':
        return path
    if active_lang_codes:
        parts = path.lstrip('/').split('/', 1)
        if parts[0].lower() in active_lang_codes:
            return '/' + parts[1] if len(parts) > 1 else '/'
    match = _LANG_PREFIX_RE.match(path)
    if match:
        tail = path[match.end():]
        return tail or '/'
    return path


def _to_relative_path(url_or_path):
    """Convert an absolute URL to its path component.

    'https://example.com/products/page' → '/products/page'
    '/products/page'                    → '/products/page'
    """
    if not url_or_path:
        return ''
    if url_or_path.startswith('http'):
        try:
            from urllib.parse import urlparse
            return urlparse(url_or_path).path or '/'
        except Exception:
            pass
    return url_or_path


def _normalize_schema_target_url(url_or_path):
    """Return the canonical stored URL target used for matching records."""
    path = _to_relative_path((url_or_path or '').strip())
    if not path:
        return ''
    if not path.startswith('/'):
        path = '/' + path
    if path != '/':
        path = path.rstrip('/')
    return path


def _datetime_to_schema(value):
    if not value:
        return ''
    try:
        return fields.Datetime.to_datetime(value).replace(microsecond=0).isoformat()
    except Exception:
        return str(value)


def _infer_schema_field_type(field_key):
    key = (field_key or '').lower()
    last_part = key.split('.')[-1]
    if key in ('sameas', 'itemlistelement', 'availablelanguage', 'haspart'):
        return 'json'
    if any(token in last_part for token in ('url', 'image', 'logo')) or last_part in ('@id', 'id'):
        return 'url'
    if any(token in key for token in ('description', 'text', 'answer', 'articlebody')):
        return 'text'
    if any(token in key for token in ('price', 'ratingvalue', 'latitude', 'longitude')):
        return 'float'
    if any(token in key for token in ('numberofitems', 'reviewcount', 'position', 'count')):
        return 'integer'
    return 'char'


def _schema_field_label(field_key):
    labels = {
        'name': 'Name',
        'description': 'Description',
        'image': 'Image URL',
        'logo': 'Logo URL',
        'url': 'Schema URL / Canonical URL',
        'sku': 'SKU',
        'category': 'Category',
        'brand.@id': 'Brand Organization ID',
        'manufacturer.@id': 'Manufacturer Organization ID',
        'offers.url': 'Offer URL',
        'offers.availability': 'Availability',
        'offers.priceSpecification.priceCurrency': 'Currency',
        'offers.priceSpecification.description': 'Price Description',
        'inLanguage': 'Language',
        'sameAs': 'Same As Links',
        'availableLanguage': 'Available Languages',
        'openingHoursSpecification': 'Opening Hours',
        'geo.latitude': 'Latitude',
        'geo.longitude': 'Longitude',
    }
    if field_key in labels:
        return labels[field_key]
    label = (field_key or '').replace('@', '').replace('.', ' / ').replace('_', ' ')
    return label.title()


# ---------------------------------------------------------------------------
# P7 — Nested dot-path helpers
# ---------------------------------------------------------------------------

def _set_nested_value(data, path, value):
    """Set *value* at a dot-path key within *data*.

    'name'                            → data['name'] = value
    'offers.price'                    → data['offers']['price'] = value
    'brand.@id'                       → data['brand']['@id'] = value
    'offers.priceSpecification.price' → three levels deep
    """
    if '.' not in path:
        data[path] = value
        return
    parts = path.split('.')
    node = data
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def _get_nested_value(data, path):
    """Return value at a dot-path key within *data*, or None if absent."""
    if not isinstance(data, dict):
        return None
    if '.' not in path:
        return data.get(path)
    node = data
    for part in path.split('.'):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


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
    target_url = fields.Char(
        'Render URL / Target URL',
        help='This controls where the schema is rendered. Use /page-url, /tr/page-url, or a full https://example.com/page-url URL.',
    )
    lang_code = fields.Char('Language Code', required=False,
                             help='This schema record renders only for this website language. Use a BCP 47 code such as en, no, or de. Leave blank to apply to all languages.')
    schema_template_id = fields.Many2one(
        'midvex.schema.template', string='Schema Template', ondelete='set null',
        help='Start by selecting a schema template, such as Product, FAQPage, BreadcrumbList, Article, or Service.'
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
    resolved_url_preview = fields.Char(
        'Resolved URL Preview', compute='_compute_target_display', store=False
    )
    render_target_summary = fields.Char(
        'Render Target', compute='_compute_target_display', store=False
    )
    website_page_published = fields.Boolean(
        'Page Published', compute='_compute_website_page_info', store=False
    )
    website_page_write_date = fields.Datetime(
        'Page Last Modified', compute='_compute_website_page_info', store=False
    )
    website_page_create_date = fields.Datetime(
        'Page Created On', compute='_compute_website_page_info', store=False
    )
    website_page_write_uid = fields.Many2one(
        'res.users', string='Page Last Modified By',
        compute='_compute_website_page_info', store=False
    )
    website_page_create_uid = fields.Many2one(
        'res.users', string='Page Created By',
        compute='_compute_website_page_info', store=False
    )

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

    @api.depends('target_type', 'website_id', 'website_page_id', 'target_url')
    def _compute_target_display(self):
        for rec in self:
            base = ''
            if rec.website_id:
                domain = (getattr(rec.website_id, 'domain', '') or '').strip()
                if domain:
                    base = domain.rstrip('/') if domain.startswith('http') else 'https://' + domain.rstrip('/')
            path = rec.target_url or ''
            if rec.target_type == 'global':
                rec.render_target_summary = 'All pages on %s' % (rec.website_id.name or 'this website')
                rec.resolved_url_preview = base or ''
            elif rec.target_type == 'page':
                page_name = rec.website_page_id.display_name if rec.website_page_id else 'No page selected'
                rec.render_target_summary = 'Website Page: %s' % page_name
                rec.resolved_url_preview = path if _URL_RE.match(path or '') else (base + path if base and path else path)
            else:
                rec.render_target_summary = 'Custom URL: %s' % (path or 'No URL set')
                rec.resolved_url_preview = path if _URL_RE.match(path or '') else (base + path if base and path else path)

    @api.depends('website_page_id')
    def _compute_website_page_info(self):
        for rec in self:
            page = rec.website_page_id
            rec.website_page_published = bool(
                page and (
                    getattr(page, 'is_published', False)
                    or getattr(page, 'website_published', False)
                )
            )
            rec.website_page_write_date = page.write_date if page else False
            rec.website_page_create_date = page.create_date if page else False
            rec.website_page_write_uid = page.write_uid if page else False
            rec.website_page_create_uid = page.create_uid if page else False

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains('website_id', 'target_type', 'website_page_id', 'target_url',
                    'lang_code', 'schema_type')
    def _check_unique_schema_context(self):
        for rec in self:
            domain = rec._get_duplicate_domain()
            if self.search_count(domain):
                raise ValidationError(
                    f'A schema record with website "{rec.website_id.name}", '
                    f'language "{rec.lang_code}" and type "{rec.schema_type}" '
                    f'already exists for this target.'
                )

    @api.constrains('manual_json_enabled', 'manual_json')
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
            if isinstance(val, str) and '{{' in val:
                val, warnings = self.env['midvex.schema.token'].resolve_tokens(
                    val, context=self._get_token_context()
                )
                if warnings:
                    _logger.info(
                        'midvex_schema_manager: unresolved token in schema record %s: %s',
                        self.id, '; '.join(warnings),
                    )
            if val is not None and val != '' and val is not False:
                # Dot-path keys (e.g. 'offers.price', 'brand.@id') are set
                # at the correct nesting level; flat keys behave as before.
                _set_nested_value(data, fv.field_key, val)

        return data

    def _get_base_url(self):
        self.ensure_one()
        domain = ''
        if self.website_id and self.website_id.domain:
            domain = self.website_id.domain.strip()
        if domain:
            return domain.rstrip('/') if domain.startswith('http') else 'https://' + domain.rstrip('/')
        settings = self.env['midvex.schema.settings'].search([
            ('website_id', '=', self.website_id.id),
        ], limit=1)
        if settings:
            settings_base = settings._get_base_url(self.website_id)
            if settings_base:
                return settings_base
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        if base_url:
            return base_url.rstrip('/')
        try:
            from odoo.http import request
            request_base = getattr(request.httprequest, 'url_root', '') or ''
            if request_base:
                return request_base.rstrip('/')
        except Exception:
            pass
        return ''

    def _get_absolute_target_url(self):
        self.ensure_one()
        target = self.target_url or ''
        if not target:
            return ''
        if _URL_RE.match(target):
            return target
        base = self._get_base_url()
        return base + target if base else target

    def _to_absolute_url(self, url_or_path):
        self.ensure_one()
        value = (url_or_path or '').strip()
        if not value:
            return ''
        if _URL_RE.match(value):
            return value
        if value.startswith('//'):
            return 'https:' + value
        if not value.startswith('/'):
            value = '/' + value
        base = self._get_base_url()
        return base + value if base else value

    def _get_schema_settings(self):
        self.ensure_one()
        return self.env['midvex.schema.settings'].search([
            ('website_id', '=', self.website_id.id),
        ], limit=1)

    def _get_default_image_url(self):
        self.ensure_one()
        settings = self._get_schema_settings()
        if settings and settings.default_image_url:
            return self._to_absolute_url(settings.default_image_url)
        return ''

    def _get_company_name(self):
        self.ensure_one()
        if self.website_id and 'company_id' in self.website_id._fields and self.website_id.company_id:
            return self.website_id.company_id.name
        return self.env.company.name

    def _get_token_context(self):
        self.ensure_one()
        absolute_url = self._get_absolute_target_url()
        return {
            'website': self.website_id,
            'company': self.website_id.company_id if self.website_id and 'company_id' in self.website_id._fields else self.env.company,
            'page': self.website_page_id,
            'current': {
                'url': absolute_url,
                'path': _to_relative_path(self.target_url or absolute_url),
                'lang': self.lang_code,
                'canonical_url': absolute_url,
            },
        }

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
        if self.manual_json_enabled and not self.manual_json:
            return None
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

        if self.manual_json_enabled and not self.manual_json:
            errors.append('Manual JSON override is enabled, but Manual JSON is empty.')
        elif not isinstance(data, dict):
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

            # --- P6: template-driven required-field validation (non-empty) ---
            if self.schema_template_id:
                for field_path in self.schema_template_id.get_required_fields():
                    val = _get_nested_value(data, field_path)
                    if val is None or val == '' or val == [] or val == {}:
                        if field_path == 'image' and self.schema_type != 'Product':
                            warnings.append(
                                'Field "image" is empty. Add a page SEO image or configure Global Website Schema default image.'
                            )
                        else:
                            errors.append(
                                f'Required field "{field_path}" is missing or empty.'
                            )

            # --- Schema-type-specific checks (also used when no template) ---
            if self.schema_type == 'Product':
                for req in ('name', 'description', 'image'):
                    if not _get_nested_value(data, req):
                        message = f'Product: "{req}" is required and must be non-empty.'
                        if message not in errors:
                            errors.append(message)
                if not _get_nested_value(data, 'url'):
                    warnings.append('Product: "url" is recommended for Google Merchant readiness.')
                if not (_get_nested_value(data, 'brand.@id') or _get_nested_value(data, 'brand.name')):
                    warnings.append('Product: brand is recommended for Google Merchant readiness.')
                if _get_nested_value(data, 'offers.price') and not _get_nested_value(data, 'offers.priceCurrency') and not _get_nested_value(data, 'offers.priceSpecification.priceCurrency'):
                    warnings.append('Product: price is set but currency is missing.')

            elif self.schema_type == 'FAQPage':
                if not self.faq_item_ids.filtered(lambda f: f.active):
                    errors.append('FAQPage requires at least one active FAQ item.')

            elif self.schema_type == 'BreadcrumbList':
                if not self.breadcrumb_item_ids:
                    errors.append('BreadcrumbList requires at least one breadcrumb item.')
                else:
                    positions = sorted(self.breadcrumb_item_ids.mapped('position'))
                    if positions != list(range(1, len(positions) + 1)):
                        warnings.append(
                            'BreadcrumbList item positions should be sequential starting from 1.'
                        )

            elif self.schema_type in ('Organization', 'WebSite'):
                for req in ('name', 'url'):
                    if not _get_nested_value(data, req):
                        warnings.append(f'{self.schema_type}: "{req}" is recommended.')
                if self.target_type == 'url':
                    warnings.append(
                        '%s schema is normally global. Use Target Type = Global unless this is an intentional advanced override.'
                        % self.schema_type
                    )
            elif self.schema_type in ('LocalBusiness', 'ProfessionalService', 'MedicalBusiness', 'Dentist'):
                if not (
                    _get_nested_value(data, 'address.streetAddress')
                    or _get_nested_value(data, 'address.addressLocality')
                    or _get_nested_value(data, 'address.addressCountry')
                ):
                    warnings.append('%s: address fields are recommended for local SEO.' % self.schema_type)
                if not (_get_nested_value(data, 'telephone') or _get_nested_value(data, 'email')):
                    warnings.append('%s: telephone or email is recommended for local SEO.' % self.schema_type)

            unresolved = []
            for fv in self.field_value_ids:
                val = fv.get_value()
                if isinstance(val, str) and '{{' in val:
                    _resolved, token_warnings = self.env['midvex.schema.token'].resolve_tokens(
                        val, context=self._get_token_context()
                    )
                    unresolved.extend(token_warnings)
            warnings.extend(unresolved)

            if self.target_type == 'global' and self.schema_type in ('Organization', 'WebSite'):
                settings = self.env['midvex.schema.settings'].search([
                    ('website_id', '=', self.website_id.id),
                    ('enable_global_schema', '=', True),
                ], limit=1)
                if settings:
                    warnings.append(
                        'Global Website Schema is enabled for this website. Avoid duplicate global %s schema unless you have a specific reason.'
                        % self.schema_type
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

    def action_format_manual_json(self):
        for record in self:
            if record.manual_json:
                parsed = json.loads(record.manual_json)
                record.manual_json = json.dumps(parsed, ensure_ascii=False, indent=2)
        return True

    def action_validate_manual_json(self):
        self.ensure_one()
        if not self.manual_json:
            raise ValidationError('Manual JSON is empty.')
        json.loads(self.manual_json)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'JSON is valid',
                'message': 'Manual JSON override is valid JSON.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_rich_results_test(self):
        self.ensure_one()
        url = self._get_absolute_target_url()
        test_url = 'https://search.google.com/test/rich-results'
        if url:
            test_url += '?url=' + url
        return {
            'type': 'ir.actions.act_url',
            'url': test_url,
            'target': 'new',
        }

    def action_open_schema_validator(self):
        return {
            'type': 'ir.actions.act_url',
            'url': 'https://validator.schema.org/',
            'target': 'new',
        }

    def action_open_website_url(self):
        self.ensure_one()
        url = self._get_absolute_target_url()
        if not url:
            raise ValidationError('No target URL is configured for this schema record.')
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_open_website_page_backend(self):
        self.ensure_one()
        if not self.website_page_id:
            raise ValidationError('No website page is attached to this schema record.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Website Page',
            'res_model': 'website.page',
            'view_mode': 'form',
            'res_id': self.website_page_id.id,
            'target': 'current',
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
        candidates = self._get_auto_populate_candidates()
        if not candidates:
            return False
        self._apply_auto_populate_candidates(candidates)
        return True

    def _get_auto_populate_candidates(self):
        self.ensure_one()
        page = self.website_page_id
        if not page:
            return {}
        view = page.view_id
        meta_title = ''
        meta_description = ''
        image = ''
        if view:
            meta_title = (
                getattr(view, 'website_meta_title', '') or
                getattr(view, 'name', '') or
                getattr(page, 'name', '')
            )
            meta_description = getattr(view, 'website_meta_description', '') or ''
            image = (
                getattr(view, 'website_meta_og_img', '') or
                getattr(view, 'website_meta_image', '') or
                getattr(view, 'website_meta_og_image', '')
            )
        if image:
            image = self._to_absolute_url(image)
        else:
            image = self._get_default_image_url()

        candidates = {
            'name': meta_title,
            'description': meta_description,
            'url': self._get_absolute_target_url() or self.target_url or '',
            'inLanguage': self.lang_code,
        }
        if image:
            candidates['image'] = image

        if self.schema_type in ('Article', 'BlogPosting'):
            author_name = self._get_company_name()
            candidates.update({
                'headline': meta_title,
                'datePublished': _datetime_to_schema(getattr(view, 'create_date', False) if view else page.create_date),
                'dateModified': _datetime_to_schema(getattr(view, 'write_date', False) if view else page.write_date),
                'author.name': author_name,
                'publisher.name': self._get_company_name(),
            })
            settings = self._get_schema_settings()
            logo = settings.logo_url if settings and settings.logo_url else ''
            if logo:
                candidates['publisher.logo.url'] = self._to_absolute_url(logo)

        if self.schema_type == 'Product':
            settings = self._get_schema_settings()
            base = settings._get_base_url(self.website_id) if settings else self._get_base_url()
            if not base:
                base = self._get_base_url()
            if base:
                candidates.setdefault('brand.@id', base + '/#organization')
                candidates.setdefault('manufacturer.@id', base + '/#organization')
            candidates.setdefault('offers.availability', 'https://schema.org/LimitedAvailability')
            candidates.setdefault('offers.priceSpecification.priceCurrency', '')
            candidates.setdefault('offers.priceSpecification.description', 'Price available upon request.')
            candidates.setdefault('offers.url', candidates.get('url', ''))

        if self.schema_template_id:
            for schema_field, odoo_key in self.schema_template_id.get_auto_mapping().items():
                if odoo_key in candidates and candidates[odoo_key]:
                    candidates[schema_field] = candidates[odoo_key]
        return candidates

    def _get_field_value_vals(self, field_key, value):
        field_type = _infer_schema_field_type(field_key)
        vals = {
            'field_type': field_type,
            'value_char': False,
            'value_text': False,
            'value_html': False,
            'value_url': False,
            'value_boolean': False,
            'value_integer': False,
            'value_float': False,
            'value_json': False,
        }
        if field_type == 'url':
            vals['value_url'] = self._to_absolute_url(value)
        elif field_type == 'text':
            vals['value_text'] = value
        else:
            vals['value_char'] = value
        return vals

    def _apply_auto_populate_candidates(self, candidates):
        self.ensure_one()
        for field_key, value in candidates.items():
            if not value:
                continue
            field_type = _infer_schema_field_type(field_key)
            existing = self.field_value_ids.filtered(lambda v: v.field_key == field_key)
            if existing:
                existing[0].write(self._get_field_value_vals(field_key, value))
            else:
                self.env['midvex.schema.field.value'].create({
                    'schema_record_id': self.id,
                    'field_key': field_key,
                    'field_label': _schema_field_label(field_key),
                    'field_type': field_type,
                    'value_char': value if field_type == 'char' else False,
                    'value_text': value if field_type == 'text' else False,
                    'value_url': self._to_absolute_url(value) if field_type == 'url' else False,
                    'lang_code': False,
                })

    def action_add_required_fields(self):
        for record in self:
            record._add_template_fields(required=True, optional=False)
        return True

    def action_add_optional_fields(self):
        for record in self:
            record._add_template_fields(required=False, optional=True)
        return True

    def action_suggest_breadcrumbs(self):
        for record in self:
            crumbs = record.suggest_breadcrumbs_from_url(record.target_url or '/')
            record.breadcrumb_item_ids = [Command.clear()] + [
                Command.create({
                    'position': index,
                    'name': crumb['name'],
                    'url': crumb['url'],
                    'lang_code': False,
                })
                for index, crumb in enumerate(crumbs, start=1)
            ]
        return True

    def action_add_sample_faq(self):
        for record in self:
            next_position = max(record.faq_item_ids.mapped('position') or [0]) + 1
            record.faq_item_ids = [Command.create({
                'position': next_position,
                'question': 'New question',
                'answer': 'Replace this answer with FAQ content that is visible on the page.',
                'lang_code': False,
                'active': True,
            })]
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
        - Global Website Schema Organization/WebSite schema is rendered first.
        - Dynamic Model Mappings follow (if no static overrides exist).
        - Page/URL-specific records follow, sorted by priority desc.
        """
        try:
            website = getattr(request, 'website', None)
            if not website:
                website = request.env['website'].get_current_website()

            # Resolve language: prefer request.lang, fallback to env lang
            lang = getattr(request, 'lang', None)
            odoo_lang_code = ''
            if lang and hasattr(lang, 'code'):
                odoo_lang_code = lang.code
            elif getattr(request, 'env', None) and request.env.lang:
                odoo_lang_code = request.env.lang
            lang_code = _get_schema_lang_code(odoo_lang_code)

            raw_path = (
                getattr(request.httprequest, 'path', '')
                if hasattr(request, 'httprequest')
                else ''
            )
            # Strip language prefix using website's active language codes
            active_lang_codes = _get_active_language_url_codes(website)
            current_path = _strip_language_prefix(raw_path, active_lang_codes)
        except Exception as exc:
            _logger.warning('midvex_schema_manager: could not resolve request context: %s', exc)
            return Markup('')

        parts = []

        # ── 1. Global Website Schema: Organization + WebSite @graph ───
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

        # ── 2. Query Page / URL Static records ────────
        base_domain = [
            ('active', '=', True),
            ('website_id', 'in', [False, website.id]),
            ('lang_code', 'in', [False, lang_code]),
        ]

        global_records = self.sudo().search(
            base_domain + [('target_type', '=', 'global')]
        )

        base_url = ''
        domain = (getattr(website, 'domain', '') or '').strip()
        if domain:
            base_url = domain.rstrip('/') if domain.startswith('http') else 'https://' + domain.rstrip('/')

        # Page matching: use normalized path, scoped by website when supported
        page_domain = [('url', 'in', list({current_path, raw_path} - {''}))]
        if 'website_id' in self.env['website.page']._fields:
            page_domain.append(('website_id', 'in', [False, website.id]))
        matching_pages = self.env['website.page'].sudo().search(page_domain)
        page_records = self.sudo().search(
            base_domain + [
                ('target_type', '=', 'page'),
                ('website_page_id', 'in', matching_pages.ids),
            ]
        )

        # URL matching: raw/normalized relative paths and absolute equivalents
        url_candidates = {
            current_path,
            raw_path,
            _to_relative_path(current_path),
            _normalize_schema_target_url(current_path),
            _normalize_schema_target_url(raw_path),
        }
        if base_url:
            url_candidates.update({
                base_url + current_path if current_path else '',
                base_url + raw_path if raw_path else '',
                _normalize_schema_target_url(base_url + current_path) if current_path else '',
                _normalize_schema_target_url(base_url + raw_path) if raw_path else '',
            })
        url_search_paths = list(url_candidates - {''})
        url_records = self.sudo().search(
            base_domain + [
                ('target_type', '=', 'url'),
                ('target_url', 'in', url_search_paths),
            ]
        ) if url_search_paths else self.env['midvex.schema.record']

        # ── 3. Dynamic Model Mappings (fallback when no specific static schema overrides exist) ───
        if not page_records and not url_records:
            try:
                main_object = None
                if getattr(request, 'env', None) and request.env.context.get('main_object'):
                    main_object = request.env.context.get('main_object')
                elif hasattr(request, 'main_object') and request.main_object:
                    main_object = request.main_object
                
                if not main_object and hasattr(request, 'route_parameters') and request.route_parameters:
                    for param_val in request.route_parameters.values():
                        if isinstance(param_val, models.BaseModel) and len(param_val) == 1:
                            if param_val._name != 'website':
                                main_object = param_val
                                break
                                
                if main_object:
                    mapping = self.env['midvex.schema.mapping'].sudo().search([
                        ('active', '=', True),
                        ('target_model_id.model', '=', main_object._name)
                    ], limit=1)
                    if not mapping:
                        mapping = self.env['midvex.schema.mapping'].sudo().search([
                            ('active', '=', True),
                            ('target_model', '=', main_object._name)
                        ], limit=1)
                        
                    if mapping:
                        current_url = base_url + raw_path if base_url else raw_path
                        current_dict = {
                            'url': current_url,
                            'path': raw_path,
                            'lang': lang_code,
                            'canonical_url': current_url,
                        }
                        token_context = {
                            'website': website,
                            'company': website.company_id if 'company_id' in website._fields and website.company_id else request.env.company,
                            'current': current_dict,
                        }
                        if main_object._name in ('product.template', 'product.product'):
                            token_context['product'] = main_object
                        elif main_object._name == 'blog.post':
                            token_context['blog'] = main_object
                        elif main_object._name == 'website.page':
                            token_context['page'] = main_object
                            
                        data = mapping.build_schema_data(main_object, context=token_context)
                        if data:
                            parts.append(_build_jsonld_script(data))
            except Exception as exc:
                _logger.error(
                    'midvex_schema_manager: error rendering dynamic model mapping: %s', exc
                )

        # ── 4. Render Static schemas (sorted by priority desc) ───
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
        path = _to_relative_path(url).split('?')[0].rstrip('/')
        path = _strip_language_prefix(path, set())
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
        domain = self._get_duplicate_domain()
        duplicates = self.search(domain)
        warnings = []
        if duplicates:
            names = ', '.join(duplicates.mapped('name'))
            warnings.append(f'Possible duplicate schema found: {names}')
        if self.target_type == 'global' and self.schema_type in ('Organization', 'WebSite'):
            settings = self.env['midvex.schema.settings'].search([
                ('website_id', '=', self.website_id.id),
                ('enable_global_schema', '=', True),
            ], limit=1)
            if settings:
                warnings.append(
                    'Global Website Schema already renders Organization/WebSite data for this website.'
                )
        return '\n'.join(warnings)

    def _get_duplicate_domain(self):
        self.ensure_one()
        domain = [
            ('id', '!=', self.id or 0),
            ('active', '=', True),
            ('website_id', '=', self.website_id.id),
            ('lang_code', '=', self.lang_code),
            ('schema_type', '=', self.schema_type),
        ]
        if self.target_type == 'global':
            return domain + [('target_type', '=', 'global')]
        if self.target_type == 'page':
            if self.website_page_id:
                urls = {
                    _normalize_schema_target_url(self.website_page_id.url),
                    _normalize_schema_target_url(self.target_url),
                } - {''}
                return domain + [
                    ('target_type', 'in', ['page', 'url']),
                    '|',
                    ('website_page_id', '=', self.website_page_id.id),
                    ('target_url', 'in', list(urls) or ['__no_url__']),
                ]
            if self.target_url:
                normalized_url = _normalize_schema_target_url(self.target_url)
                pages = self.env['website.page'].search([('url', '=', normalized_url)])
                return domain + [
                    ('target_type', 'in', ['page', 'url']),
                    '|',
                    ('target_url', '=', normalized_url),
                    ('website_page_id', 'in', pages.ids or [0]),
                ]
            raise ValidationError('Website Page or Target URL is required for page schema records.')
        if self.target_type == 'url':
            if not self.target_url:
                raise ValidationError('Target URL is required for custom URL schema records.')
            normalized_url = _normalize_schema_target_url(self.target_url)
            pages = self.env['website.page'].search([('url', '=', normalized_url)])
            return domain + [
                ('target_type', 'in', ['page', 'url']),
                '|',
                ('target_url', '=', normalized_url),
                ('website_page_id', 'in', pages.ids or [0]),
            ]
        return domain

    @api.onchange('schema_template_id')
    def _onchange_schema_template_id(self):
        if not self.schema_template_id:
            return
        self.schema_type = self.schema_template_id.schema_type
        self.target_type = self.schema_template_id.get_recommended_target_type()
        commands = [Command.clear()] + self._prepare_template_field_commands(
            required=True, optional=False, ignore_existing=True
        )
        if self.schema_template_id.load_optional_fields_by_default:
            commands += self._prepare_template_field_commands(
                required=False, optional=True, ignore_existing=True
            )
        self.field_value_ids = commands
        if self.schema_type in ('Organization', 'WebSite') and self.target_type == 'url':
            return {
                'warning': {
                    'title': 'Global schema recommended',
                    'message': '%s is normally rendered globally. Use Custom URL only for an intentional advanced override.' % self.schema_type,
                }
            }

    @api.onchange('website_page_id')
    def _onchange_website_page_id(self):
        if self.website_page_id:
            self.target_url = _normalize_schema_target_url(self.website_page_id.url)
            if self.auto_populate:
                commands = []
                candidates = self._get_auto_populate_candidates()
                for field_key, value in candidates.items():
                    if not value:
                        continue
                    existing = self.field_value_ids.filtered(lambda v: v.field_key == field_key)[:1]
                    vals = self._get_field_value_vals(field_key, value)
                    if existing:
                        commands.append(Command.update(existing.id, vals))
                    else:
                        field_type = _infer_schema_field_type(field_key)
                        commands.append(Command.create({
                            'field_key': field_key,
                            'field_label': _schema_field_label(field_key),
                            'field_type': field_type,
                            'value_char': value if field_type == 'char' else False,
                            'value_text': value if field_type == 'text' else False,
                            'value_url': self._to_absolute_url(value) if field_type == 'url' else False,
                            'lang_code': False,
                        }))
                if commands:
                    self.field_value_ids = commands

    def _prepare_template_field_commands(self, required=True, optional=False, ignore_existing=False):
        self.ensure_one()
        if not self.schema_template_id:
            return []
        field_keys = []
        required_keys = set(self.schema_template_id.get_required_fields()) if required else set()
        if required:
            field_keys.extend(self.schema_template_id.get_required_fields())
        if optional:
            field_keys.extend(self.schema_template_id.get_optional_fields())

        existing_keys = set() if ignore_existing else set(self.field_value_ids.mapped('field_key'))
        commands = []
        sequence = 10
        for field_key in field_keys:
            if field_key in existing_keys:
                continue
            commands.append(Command.create({
                'field_key': field_key,
                'field_label': _schema_field_label(field_key),
                'field_type': _infer_schema_field_type(field_key),
                'required': field_key in required_keys,
                'sequence': sequence,
            }))
            sequence += 10
        return commands

    def _add_template_fields(self, required=True, optional=False):
        self.ensure_one()
        commands = self._prepare_template_field_commands(required=required, optional=optional)
        if commands:
            self.write({'field_value_ids': commands})

    def action_reset_fields_from_template(self):
        for record in self:
            if not record.schema_template_id:
                continue
            template_keys = set(record.schema_template_id.get_required_fields())
            if record.schema_template_id.load_optional_fields_by_default:
                template_keys.update(record.schema_template_id.get_optional_fields())
            required_keys = set(record.schema_template_id.get_required_fields())
            for line in record.field_value_ids.filtered(lambda item: item.field_key in template_keys):
                line.write({
                    'field_label': _schema_field_label(line.field_key),
                    'field_type': _infer_schema_field_type(line.field_key),
                    'required': line.field_key in required_keys,
                })
            commands = record._prepare_template_field_commands(
                required=True, optional=record.schema_template_id.load_optional_fields_by_default
            )
            if commands:
                record.write({'field_value_ids': commands})
        return True

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
        for vals in vals_list:
            template_id = vals.get('schema_template_id')
            if template_id:
                template = self.env['midvex.schema.template'].browse(template_id)
                if not vals.get('schema_type'):
                    vals['schema_type'] = template.schema_type
                if not vals.get('target_type'):
                    vals['target_type'] = template.get_recommended_target_type()
            if vals.get('target_url'):
                vals['target_url'] = _normalize_schema_target_url(vals['target_url'])
        records = super().create(vals_list)
        for record in records:
            if record.schema_template_id and not record.field_value_ids:
                record._add_template_fields(required=True, optional=False)
                if record.schema_template_id.load_optional_fields_by_default:
                    record.action_add_optional_fields()
            if record.schema_template_id and record.target_type == 'url' and record.schema_type in ('Organization', 'WebSite'):
                super(MidvexSchemaRecord, record).write({
                    'duplicate_warning': '%s schema is normally global. Use Target Type = Global unless this is intentional.' % record.schema_type
                })
            warning = record.check_duplicate_schema()
            if warning:
                super(MidvexSchemaRecord, record).write({'duplicate_warning': warning})
        return records

    def write(self, vals):
        if vals.get('schema_template_id'):
            template = self.env['midvex.schema.template'].browse(vals['schema_template_id'])
            vals.setdefault('schema_type', template.schema_type)
        if vals.get('target_url'):
            vals['target_url'] = _normalize_schema_target_url(vals['target_url'])
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
