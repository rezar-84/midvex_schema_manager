from odoo.tests.common import TransactionCase
from odoo.tests import tagged


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
                (0, 0, {
                    'schema_field_path': 'name',
                    'source_type': 'token',
                    'token': '{{ page.name }}',
                }),
                (0, 0, {
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
                (0, 0, {
                    'field_key': 'name',
                    'field_type': 'char',
                    'value_char': '{{ website.name }}',
                }),
            ],
        })
        data = record.build_schema_data()
        self.assertEqual(data['name'], self.website.name)
