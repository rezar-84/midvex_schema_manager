from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo import Command


@tagged('post_install', '-at_install', 'midvex_schema')
class TestSchemaTokenMapping(TransactionCase):

    def setUp(self):
        super().setUp()
        self.website = self.env.ref('website.default_website')

    def test_token_resolver_known_tokens(self):
        resolved, warnings = self.env['midvex.schema.token'].resolve_tokens(
            '{{ website.name }} - {{ current.path }}',
            context={
                'website': self.website,
                'current': {'path': '/about'},
            },
        )
        self.assertIn(self.website.name, resolved)
        self.assertIn('/about', resolved)
        self.assertEqual(warnings, [])

    def test_token_resolver_unknown_token_warning(self):
        resolved, warnings = self.env['midvex.schema.token'].resolve_tokens(
            'Keep {{ unknown.value }}',
            context={'website': self.website},
        )
        self.assertEqual(resolved, 'Keep {{ unknown.value }}')
        self.assertIn('Unknown token "{{ unknown.value }}".', warnings)

    def test_product_token_requires_product_context(self):
        resolved, warnings = self.env['midvex.schema.token'].resolve_tokens(
            '{{ product.name }}',
            context={'website': self.website},
        )
        self.assertEqual(resolved, '')
        self.assertEqual(warnings, [])

    def test_mapping_engine_builds_nested_json(self):
        template = self.env.ref('midvex_schema_manager.schema_template_product')
        mapping = self.env['midvex.schema.mapping'].create({
            'name': 'Page Product Mapping',
            'target_model': 'website.page',
            'schema_template_id': template.id,
            'line_ids': [
                Command.create({
                    'schema_field_path': 'name',
                    'source_type': 'token',
                    'token': '{{ page.name }}',
                }),
                Command.create({
                    'schema_field_path': 'brand.@id',
                    'source_type': 'token',
                    'token': '{{ current.canonical_url }}#brand',
                }),
            ],
        })
        page = self.env['website.page'].search([], limit=1)
        data = mapping.build_schema_data(page, context={
            'website': self.website,
            'page': page,
            'current': {'canonical_url': 'https://example.com/product'},
        })
        self.assertEqual(data['@type'], 'Product')
        self.assertEqual(data['brand']['@id'], 'https://example.com/product#brand')

    def test_record_build_resolves_tokens(self):
        record = self.env['midvex.schema.record'].create({
            'name': 'Token Schema',
            'website_id': self.website.id,
            'target_type': 'url',
            'target_url': '/token-schema',
            'lang_code': 'en',
            'schema_type': 'WebPage',
            'field_value_ids': [
                Command.create({
                    'field_key': 'name',
                    'field_type': 'char',
                    'value_char': '{{ website.name }}',
                }),
            ],
        })
        data = record.build_schema_data()
        self.assertEqual(data['name'], self.website.name)

    def test_model_mapping_frontend_rendering(self):
        # 1. Create dummy request-like object
        class DummyHttpRequest:
            def __init__(self):
                self.path = '/shop/product/dummy-product'
                
        class DummyRequest:
            def __init__(self, env):
                self.env = env
                self.website = env.ref('website.default_website')
                self.httprequest = DummyHttpRequest()
                self.lang = env['res.lang'].search([('active', '=', True)], limit=1)
                self.route_parameters = {}
                
        req = DummyRequest(self.env)
        
        # 2. Find or create a product template
        product = self.env['product.template'].search([], limit=1)
        if not product:
            product = self.env['product.template'].create({
                'name': 'Test Mapping Product',
                'list_price': 99.99,
            })
            
        req.route_parameters['product'] = product
        
        # 3. Create a mapping for product.template
        template = self.env.ref('midvex_schema_manager.schema_template_product')
        mapping = self.env['midvex.schema.mapping'].create({
            'name': 'Test Product Template Mapping',
            'target_model_id': self.env['ir.model'].search([('model', '=', 'product.template')], limit=1).id,
            'schema_template_id': template.id,
            'line_ids': [
                Command.create({
                    'schema_field_path': 'name',
                    'source_type': 'odoo_field',
                    'odoo_field_id': self.env['ir.model.fields'].search([
                        ('model_id.model', '=', 'product.template'),
                        ('name', '=', 'name')
                    ], limit=1).id,
                }),
                Command.create({
                    'schema_field_path': 'offers.price',
                    'source_type': 'odoo_field',
                    'odoo_field_id': self.env['ir.model.fields'].search([
                        ('model_id.model', '=', 'product.template'),
                        ('name', '=', 'list_price')
                    ], limit=1).id,
                }),
            ]
        })
        
        # 4. Render schema for request
        res = self.env['midvex.schema.record'].render_schema_for_request(req)
        
        # 5. Verify script matches expectations
        self.assertIn('"@type": "Product"', res)
        self.assertIn(f'"name": "{product.name}"', res)
        self.assertIn('"price":', res)

