from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo import Command

from ..models.schema_record import _strip_language_prefix, _get_schema_lang_code


@tagged('post_install', '-at_install', 'midvex_schema')
class TestRendering(TransactionCase):

    def setUp(self):
        super().setUp()
        self.website = self.env.ref('website.default_website')
        self.en_record = self.env['midvex.schema.record'].create({
            'name': 'EN Page Schema',
            'website_id': self.website.id,
            'target_type': 'url',
            'target_url': '/products/page',
            'lang_code': 'en',
            'schema_type': 'WebPage',
        })

    def test_english_schema_not_on_turkish_page(self):
        # Simulate Turkish request: lang_code='tr', path='/tr/products/page'
        lang_code = _get_schema_lang_code('tr_TR')
        self.assertEqual(lang_code, 'tr')
        records = self.env['midvex.schema.record'].search([
            ('website_id', '=', self.website.id),
            ('target_url', '=', '/products/page'),
            ('lang_code', '=', lang_code),
        ])
        self.assertNotIn(self.en_record, records,
                         'EN schema must not render on TR page')

    def test_normalized_path_matches_record(self):
        codes = {'en', 'tr'}
        normalized = _strip_language_prefix('/tr/products/page', codes)
        self.assertEqual(normalized, '/products/page')

    def test_lang_wizard_clears_child_lang_codes(self):
        self.env['midvex.schema.field.value'].create({
            'schema_record_id': self.en_record.id,
            'field_key': 'name',
            'field_type': 'char',
            'value_char': 'Product',
            'lang_code': 'en',
        })
        wizard = self.env['midvex.schema.lang.wizard'].create({
            'schema_record_id': self.en_record.id,
            'language_ids': [Command.set(self.env['res.lang'].search([
                ('active', '=', True), ('code', 'like', 'tr')
            ]).ids)],
        })
        # Only run if Turkish language is active
        if wizard.language_ids:
            wizard.action_create_for_languages()
            tr_record = self.env['midvex.schema.record'].search([
                ('website_id', '=', self.website.id),
                ('target_url', '=', '/products/page'),
                ('lang_code', '=', 'tr'),
            ], limit=1)
            if tr_record:
                for fv in tr_record.field_value_ids:
                    self.assertFalse(fv.lang_code,
                                     'Child field values must have lang_code=False after wizard copy')

    def test_manual_json_xss_escaped(self):
        record = self.env['midvex.schema.record'].create({
            'name': 'XSS Test',
            'website_id': self.website.id,
            'target_type': 'url',
            'target_url': '/xss-test',
            'lang_code': 'en',
            'schema_type': 'WebPage',
            'manual_json_enabled': True,
            'manual_json': '{"@context":"https://schema.org","@type":"WebPage","name":"</script><script>alert(1)</script>"}',
        })
        data = record.build_schema_data()
        from ..models.json_utils import _build_jsonld_script
        script = _build_jsonld_script(data)
        # The dangerous sequence must be escaped
        self.assertNotIn('</script><script>', script)
