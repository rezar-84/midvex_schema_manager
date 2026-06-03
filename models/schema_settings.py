import json
from odoo import api, fields, models

from .json_utils import _build_jsonld_script


class MidvexSchemaSettings(models.Model):
    _name = 'midvex.schema.settings'
    _description = 'Midvex Global Website Schema Settings'
    _rec_name = 'organization_name'
    _order = 'website_id'

    website_id = fields.Many2one(
        'website', string='Website', required=True, ondelete='cascade',
        default=lambda self: self.env['website'].get_current_website(),
    )
    enable_global_schema = fields.Boolean('Enable Global Schema', default=True)
    organization_name = fields.Char('Organization Name')
    legal_name = fields.Char('Legal Name')
    alternate_names = fields.Char('Alternate Names', help='Comma-separated alternate names')
    logo_url = fields.Char('Logo URL')
    website_url = fields.Char('Website URL')
    email = fields.Char('Email')
    phone = fields.Char('Phone')
    street_address = fields.Char('Street Address')
    city = fields.Char('City')
    region = fields.Char('Region / State')
    postal_code = fields.Char('Postal Code')
    country_code = fields.Char('Country Code', size=2, help='ISO 3166-1 alpha-2, e.g. NO')
    same_as_links = fields.Text('Same As Links', help='One URL per line')
    default_image_url = fields.Char('Default Image URL')
    available_language_codes = fields.Char(
        'Available Language Codes', help='Comma-separated, e.g. en,no,de'
    )
    enable_website_schema = fields.Boolean('Enable WebSite Schema', default=True)
    enable_search_action = fields.Boolean('Enable SearchAction', default=False)
    global_schema_preview = fields.Text(
        'Global Schema Preview', compute='_compute_global_schema_preview', store=False
    )

    _sql_constraints = [
        ('website_unique', 'UNIQUE(website_id)',
         'Global schema settings must be unique per website.'),
    ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_same_as_list(self):
        self.ensure_one()
        if not self.same_as_links:
            return []
        return [ln.strip() for ln in self.same_as_links.splitlines() if ln.strip()]

    def _get_alternate_names_list(self):
        self.ensure_one()
        if not self.alternate_names:
            return []
        return [n.strip() for n in self.alternate_names.split(',') if n.strip()]

    def _get_language_codes_list(self):
        self.ensure_one()
        if not self.available_language_codes:
            return []
        return [c.strip() for c in self.available_language_codes.split(',') if c.strip()]

    def _get_base_url(self, website):
        """Return a normalised base URL for @id references.

        Priority:
        1. settings.website_url (explicitly configured)
        2. website.domain (Odoo website domain field)
        """
        self.ensure_one()
        if self.website_url:
            return self.website_url.rstrip('/')
        domain = (getattr(website, 'domain', '') or '').strip()
        if not domain:
            return ''
        if domain.startswith('http'):
            return domain.rstrip('/')
        return 'https://' + domain.rstrip('/')

    # ------------------------------------------------------------------
    # Schema data builders
    # ------------------------------------------------------------------

    def generate_organization_json(self):
        self.ensure_one()
        data = {
            '@context': 'https://schema.org',
            '@type': 'Organization',
        }
        if self.organization_name:
            data['name'] = self.organization_name
        if self.legal_name:
            data['legalName'] = self.legal_name
        alt_names = self._get_alternate_names_list()
        if alt_names:
            data['alternateName'] = alt_names
        if self.logo_url:
            data['logo'] = self.logo_url
        if self.website_url:
            data['url'] = self.website_url
        if self.email:
            data['email'] = self.email
        if self.phone:
            data['telephone'] = self.phone
        same_as = self._get_same_as_list()
        if same_as:
            data['sameAs'] = same_as
        if self.default_image_url:
            data['image'] = self.default_image_url

        address = {}
        if self.street_address:
            address['streetAddress'] = self.street_address
        if self.city:
            address['addressLocality'] = self.city
        if self.region:
            address['addressRegion'] = self.region
        if self.postal_code:
            address['postalCode'] = self.postal_code
        if self.country_code:
            address['addressCountry'] = self.country_code
        if address:
            address['@type'] = 'PostalAddress'
            data['address'] = address

        return data

    def generate_website_json(self):
        self.ensure_one()
        data = {
            '@context': 'https://schema.org',
            '@type': 'WebSite',
        }
        if self.organization_name:
            data['name'] = self.organization_name
        if self.website_url:
            data['url'] = self.website_url

        lang_codes = self._get_language_codes_list()
        if lang_codes:
            data['inLanguage'] = lang_codes

        if self.enable_search_action and self.website_url:
            base = self.website_url.rstrip('/')
            data['potentialAction'] = {
                '@type': 'SearchAction',
                'target': {
                    '@type': 'EntryPoint',
                    'urlTemplate': base + '/website/search?search={search_term_string}',
                },
                'query-input': 'required name=search_term_string',
            }

        return data

    # ------------------------------------------------------------------
    # Frontend rendering (read-only — no database writes)
    # ------------------------------------------------------------------

    def _build_global_graph_data(self, website, lang_code=None):
        self.ensure_one()
        base_url = self._get_base_url(website)
        graph = []

        org_data = self.generate_organization_json()
        org_data.pop('@context', None)
        if base_url:
            org_data['@id'] = base_url + '/#organization'
        graph.append(org_data)

        if self.enable_website_schema:
            web_data = self.generate_website_json()
            web_data.pop('@context', None)
            if base_url:
                web_data['@id'] = base_url + '/#website'
                web_data['publisher'] = {'@id': base_url + '/#organization'}
            try:
                lang_list = [
                    {
                        '@type': 'Language',
                        'name': lang.name,
                        'alternateName': lang.code.split('_')[0],
                    }
                    for lang in website.language_ids
                ]
                if lang_list:
                    web_data['availableLanguage'] = lang_list
            except Exception:
                pass
            graph.append(web_data)

        return {'@context': 'https://schema.org', '@graph': graph}

    def _render_global_for_website(self, website, lang_code):
        """
        Return a list with one safe JSON-LD <script> block using @graph.

        @graph wraps Organization + WebSite with cross-references via @id and
        adds availableLanguage from website.language_ids.
        Called from render_schema_for_request() — MUST NOT write to database.
        """
        settings = self.search([
            ('website_id', '=', website.id),
            ('enable_global_schema', '=', True),
        ], limit=1)
        if not settings:
            return []

        return [_build_jsonld_script(settings._build_global_graph_data(website, lang_code))]

    # ------------------------------------------------------------------
    # Backend preview
    # ------------------------------------------------------------------

    def _compute_global_schema_preview(self):
        for rec in self:
            if rec.enable_global_schema:
                try:
                    rec.global_schema_preview = json.dumps(
                        rec._build_global_graph_data(rec.website_id), ensure_ascii=False, indent=2
                    )
                    continue
                except Exception:
                    pass
            rec.global_schema_preview = 'No global schemas enabled.'
