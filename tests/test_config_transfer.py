import io
import zipfile

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'midvex_schema')
class TestSchemaConfigTransfer(TransactionCase):

    def setUp(self):
        super().setUp()
        self.wizard = self.env['midvex.schema.config.transfer.wizard'].create({
            'operation': 'import',
            'file_format': 'csv',
        })

    def test_csv_import_rejects_large_payload(self):
        with self.assertRaises(ValidationError):
            self.wizard._read_csv_zip(b'x' * (5 * 1024 * 1024 + 1))

    def test_csv_import_ignores_unknown_csv_members(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('settings.csv', 'website_name,organization_name\nDefault,Test\n')
            archive.writestr('unknown.csv', 'ignored\n1\n')
        datasets = self.wizard._read_csv_zip(stream.getvalue())
        self.assertIn('settings', datasets)
        self.assertNotIn('unknown', datasets)

    def test_csv_import_rejects_too_many_members(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for idx in range(65):
                archive.writestr('file%s.csv' % idx, 'a\nb\n')
        with self.assertRaises(ValidationError):
            self.wizard._read_csv_zip(stream.getvalue())

    def test_xlsx_import_reports_malformed_workbook_xml(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('xl/workbook.xml', '<workbook>')
            archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships/>')
        self.wizard.file_format = 'xlsx'
        with self.assertRaises(ValidationError):
            self.wizard._read_xlsx(stream.getvalue())
