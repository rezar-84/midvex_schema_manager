from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'midvex_schema')
class TestSchemaSettings(TransactionCase):

    def setUp(self):
        super().setUp()
        self.website = self.env.ref('website.default_website')
        self.settings = self.env['midvex.schema.settings'].create({
            'website_id': self.website.id,
            'enable_global_schema': True,
            'organization_name': 'Test Org',
            'website_url': 'https://test.example.com',
            'enable_website_schema': True,
        })

    def test_global_settings_generate_organization(self):
        data = self.settings.generate_organization_json()
        self.assertEqual(data['@type'], 'Organization')
        self.assertEqual(data['name'], 'Test Org')
        self.assertEqual(data['url'], 'https://test.example.com')

    def test_global_settings_generate_website(self):
        data = self.settings.generate_website_json()
        self.assertEqual(data['@type'], 'WebSite')

    def test_search_action_uses_odoo_search_route(self):
        self.settings.enable_search_action = True
        data = self.settings.generate_website_json()
        target = data['potentialAction']['target']['urlTemplate']
        self.assertIn('/website/search?search={search_term_string}', target)
        self.assertNotIn('/search?q=', target)

    def test_render_global_returns_graph(self):
        scripts = self.settings._render_global_for_website(self.website, 'en')
        self.assertEqual(len(scripts), 1)
        self.assertIn('@graph', scripts[0])
        self.assertIn('application/ld+json', scripts[0])

    def test_render_global_has_id_references(self):
        scripts = self.settings._render_global_for_website(self.website, 'en')
        script_text = scripts[0]
        self.assertIn('#organization', script_text)
        self.assertIn('#website', script_text)
        self.assertIn('publisher', script_text)

    def test_preview_matches_global_graph_shape(self):
        self.settings._compute_global_schema_preview()
        self.assertIn('@graph', self.settings.global_schema_preview)
        self.assertIn('#organization', self.settings.global_schema_preview)
        self.assertIn('publisher', self.settings.global_schema_preview)

    def test_render_global_disabled(self):
        self.settings.enable_global_schema = False
        scripts = self.settings._render_global_for_website(self.website, 'en')
        self.assertEqual(scripts, [])

    def test_no_hardcoded_domain(self):
        scripts = self.settings._render_global_for_website(self.website, 'en')
        for script in scripts:
            self.assertNotIn('varsco.com', script)
