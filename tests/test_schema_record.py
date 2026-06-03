from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..models.schema_record import (
    _get_schema_lang_code,
    _strip_language_prefix,
    _set_nested_value,
    _get_nested_value,
    _to_relative_path,
)
from ..models.json_utils import _safe_json_dumps, _build_jsonld_script


@tagged('post_install', '-at_install', 'midvex_schema')
class TestSchemaRecord(TransactionCase):

    def setUp(self):
        super().setUp()
        self.website = self.env.ref('website.default_website')
        self.record = self.env['midvex.schema.record'].create({
            'name': 'Test Product',
            'website_id': self.website.id,
            'target_type': 'url',
            'target_url': '/test-product',
            'lang_code': 'en',
            'schema_type': 'Product',
        })

    # --- P4: language code normalisation ---

    def test_get_schema_lang_code(self):
        self.assertEqual(_get_schema_lang_code('en_US'), 'en')
        self.assertEqual(_get_schema_lang_code('ko_KR'), 'ko')
        self.assertEqual(_get_schema_lang_code('tr_TR'), 'tr')
        self.assertEqual(_get_schema_lang_code(''), 'en')
        self.assertEqual(_get_schema_lang_code(None), 'en')

    def test_strip_language_prefix_with_codes(self):
        codes = {'en', 'tr', 'ko', 'ko_kr'}
        self.assertEqual(_strip_language_prefix('/tr/about', codes), '/about')
        self.assertEqual(_strip_language_prefix('/ko_KR/page', {'ko_kr'}), '/page')
        self.assertEqual(_strip_language_prefix('/no-deposit', codes), '/no-deposit')
        self.assertEqual(_strip_language_prefix('/en', codes), '/')
        self.assertEqual(_strip_language_prefix('/', codes), '/')

    def test_to_relative_path(self):
        self.assertEqual(_to_relative_path('https://example.com/products'), '/products')
        self.assertEqual(_to_relative_path('/products'), '/products')
        self.assertEqual(_to_relative_path(''), '')

    # --- P7: nested dot-path helpers ---

    def test_set_nested_value_flat(self):
        d = {}
        _set_nested_value(d, 'name', 'Test')
        self.assertEqual(d, {'name': 'Test'})

    def test_set_nested_value_deep(self):
        d = {}
        _set_nested_value(d, 'offers.price', '9.99')
        self.assertEqual(d, {'offers': {'price': '9.99'}})

    def test_set_nested_value_at_key(self):
        d = {}
        _set_nested_value(d, 'brand.@id', 'https://example.com/#brand')
        self.assertEqual(d['brand']['@id'], 'https://example.com/#brand')

    def test_set_nested_value_three_levels(self):
        d = {}
        _set_nested_value(d, 'offers.priceSpecification.priceCurrency', 'USD')
        self.assertEqual(d['offers']['priceSpecification']['priceCurrency'], 'USD')

    def test_get_nested_value(self):
        d = {'offers': {'price': '9.99'}}
        self.assertEqual(_get_nested_value(d, 'offers.price'), '9.99')
        self.assertIsNone(_get_nested_value(d, 'offers.nonexistent'))
        self.assertIsNone(_get_nested_value(d, 'missing.key'))

    def test_flat_fields_unchanged(self):
        d = {}
        _set_nested_value(d, 'name', 'Foo')
        _set_nested_value(d, 'description', 'Bar')
        self.assertEqual(d['name'], 'Foo')
        self.assertEqual(d['description'], 'Bar')

    # --- P3: XSS-safe JSON output ---

    def test_safe_json_dumps_escapes_script(self):
        data = {'name': '</script><script>alert(1)</script>'}
        result = _safe_json_dumps(data)
        self.assertNotIn('</script>', result)
        self.assertIn(r'</script>', result)

    def test_safe_json_dumps_escapes_lt_gt_amp(self):
        data = {'v': '<a>&<b>'}
        result = _safe_json_dumps(data)
        self.assertNotIn('<', result)
        self.assertNotIn('>', result)
        self.assertNotIn('&', result)

    def test_build_jsonld_script_wraps_correctly(self):
        data = {'@type': 'Product', 'name': 'Test'}
        script = _build_jsonld_script(data)
        self.assertTrue(script.startswith('<script type="application/ld+json">'))
        self.assertTrue(script.endswith('</script>'))

    # --- P2: schema rendering does not write ---

    def test_build_schema_data_no_write(self):
        self.env['midvex.schema.field.value'].create({
            'schema_record_id': self.record.id,
            'field_key': 'name',
            'field_type': 'char',
            'value_char': 'My Product',
        })
        before = self.record.write_date
        self.record.build_schema_data()
        self.record.invalidate_recordset()
        after = self.record.write_date
        self.assertEqual(before, after, 'build_schema_data() must not write to the database')

    # --- P6: validation empty-value checks ---

    def test_product_validation_fails_empty_name(self):
        self.env['midvex.schema.field.value'].create({
            'schema_record_id': self.record.id,
            'field_key': 'name',
            'field_type': 'char',
            'value_char': '',
        })
        status = self.record.validate_schema()
        self.assertEqual(status, 'error')
        self.assertIn('name', self.record.validation_message)

    def test_faqpage_fails_without_items(self):
        faq = self.env['midvex.schema.record'].create({
            'name': 'FAQ',
            'website_id': self.website.id,
            'target_type': 'url',
            'target_url': '/faq',
            'lang_code': 'en',
            'schema_type': 'FAQPage',
        })
        status = faq.validate_schema()
        self.assertEqual(status, 'error')

    def test_breadcrumb_fails_without_items(self):
        bc = self.env['midvex.schema.record'].create({
            'name': 'BC',
            'website_id': self.website.id,
            'target_type': 'url',
            'target_url': '/bc',
            'lang_code': 'en',
            'schema_type': 'BreadcrumbList',
        })
        status = bc.validate_schema()
        self.assertEqual(status, 'error')

    def test_template_first_creation_sets_type_and_required_fields(self):
        template = self.env.ref('midvex_schema_manager.schema_template_product')
        record = self.env['midvex.schema.record'].create({
            'name': 'Template First Product',
            'website_id': self.website.id,
            'target_type': 'url',
            'target_url': '/template-first-product',
            'lang_code': 'en',
            'schema_template_id': template.id,
        })
        self.assertEqual(record.schema_type, 'Product')
        required_keys = set(record.field_value_ids.filtered('required').mapped('field_key'))
        self.assertTrue({'name', 'description', 'image'}.issubset(required_keys))

    def test_breadcrumb_suggestion_from_url(self):
        crumbs = self.env['midvex.schema.record'].suggest_breadcrumbs_from_url(
            'https://example.com/products/sample-page?x=1'
        )
        self.assertEqual(crumbs[0], {'name': 'Home', 'url': '/'})
        self.assertEqual(crumbs[-1], {'name': 'Sample Page', 'url': '/products/sample-page'})

    def test_schema_manager_implies_schema_user(self):
        manager = self.env.ref('midvex_schema_manager.group_midvex_schema_manager')
        user = self.env.ref('midvex_schema_manager.group_midvex_schema_user')
        self.assertIn(user, manager.implied_ids)

    # --- P10: duplicate prevention ---

    def test_duplicate_detection(self):
        warning = self.record.check_duplicate_schema()
        self.assertEqual(warning, '', 'No duplicate should be detected for a unique record')

        self.env['midvex.schema.record'].create({
            'name': 'Duplicate',
            'website_id': self.website.id,
            'target_type': 'url',
            'target_url': '/test-product-other',
            'lang_code': 'en',
            'schema_type': 'Product',
        })
        record2 = self.env['midvex.schema.record'].create({
            'name': 'Also Product',
            'website_id': self.website.id,
            'target_type': 'url',
            'target_url': '/test-product',
            'lang_code': 'en',
            'schema_type': 'Article',  # different type, no duplicate
        })
        self.assertEqual(record2.check_duplicate_schema(), '')
