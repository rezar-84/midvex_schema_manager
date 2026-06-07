import base64
import csv
import io
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from odoo import Command, fields, models
from odoo.exceptions import ValidationError


SETTINGS_COLUMNS = [
    'website_xmlid', 'website_domain', 'website_name', 'company_name',
    'enable_global_schema', 'organization_name', 'legal_name', 'alternate_names',
    'logo_url', 'website_url', 'email', 'phone', 'street_address', 'city',
    'region', 'postal_code', 'country_code', 'same_as_links',
    'default_image_url', 'available_language_codes', 'enable_website_schema',
    'enable_search_action',
]

TEMPLATE_COLUMNS = [
    'name', 'schema_type', 'description', 'json_template',
    'required_fields_json', 'optional_fields_json', 'auto_mapping_json',
    'validation_rules_json', 'active', 'sequence', 'is_system_template',
    'load_optional_fields_by_default',
]

MAPPING_COLUMNS = [
    'name', 'target_model', 'schema_template_name', 'schema_template_type',
    'active',
]

MAPPING_LINE_COLUMNS = [
    'mapping_name', 'sequence', 'schema_field_path', 'source_type', 'token',
    'odoo_field_name', 'default_value', 'required', 'field_type',
]

_NS = {
    'main': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'rel': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}


class MidvexSchemaConfigTransferWizard(models.TransientModel):
    _name = 'midvex.schema.config.transfer.wizard'
    _description = 'Structured Data Configuration Import/Export'

    operation = fields.Selection([
        ('export', 'Export'),
        ('import', 'Import'),
    ], required=True, default='export')
    file_format = fields.Selection([
        ('xlsx', 'Excel Workbook (.xlsx)'),
        ('csv', 'CSV Files (.zip)'),
    ], required=True, default='xlsx')
    include_settings = fields.Boolean('Global Settings', default=True)
    include_templates = fields.Boolean('Templates', default=True)
    include_mappings = fields.Boolean('Model Mappings', default=True)
    import_file = fields.Binary('Import File')
    import_filename = fields.Char()
    export_file = fields.Binary('Export File', readonly=True)
    export_filename = fields.Char(readonly=True)
    message = fields.Text(readonly=True)

    def _bool_text(self, value):
        return '1' if value else '0'

    def _parse_bool(self, value):
        if isinstance(value, bool):
            return value
        return str(value or '').strip().lower() in ('1', 'true', 'yes', 'y')

    def _xmlid_for_record(self, record):
        if not record:
            return ''
        data = self.env['ir.model.data'].sudo().search([
            ('model', '=', record._name),
            ('res_id', '=', record.id),
        ], limit=1)
        return data.complete_name if data else ''

    def _resolve_website(self, row):
        xmlid = (row.get('website_xmlid') or '').strip()
        if xmlid:
            website = self.env.ref(xmlid, raise_if_not_found=False)
            if website and website._name == 'website':
                return website
        domain = (row.get('website_domain') or '').strip()
        if domain:
            website = self.env['website'].search([('domain', '=', domain)], limit=1)
            if website:
                return website
        name = (row.get('website_name') or '').strip()
        if name:
            website = self.env['website'].search([('name', '=', name)], limit=1)
            if website:
                return website
        return self.env['website'].get_current_website()

    def _resolve_company(self, row, website):
        name = (row.get('company_name') or '').strip()
        if name:
            company = self.env['res.company'].search([('name', '=', name)], limit=1)
            if company:
                return company
        return website.company_id if website and website.company_id else self.env.company

    def _export_settings_rows(self):
        rows = []
        settings = self.env['midvex.schema.settings'].search([])
        for rec in settings:
            rows.append({
                'website_xmlid': self._xmlid_for_record(rec.website_id),
                'website_domain': rec.website_id.domain or '',
                'website_name': rec.website_id.name or '',
                'company_name': rec.company_id.name or '',
                'enable_global_schema': self._bool_text(rec.enable_global_schema),
                'organization_name': rec.organization_name or '',
                'legal_name': rec.legal_name or '',
                'alternate_names': rec.alternate_names or '',
                'logo_url': rec.logo_url or '',
                'website_url': rec.website_url or '',
                'email': rec.email or '',
                'phone': rec.phone or '',
                'street_address': rec.street_address or '',
                'city': rec.city or '',
                'region': rec.region or '',
                'postal_code': rec.postal_code or '',
                'country_code': rec.country_code or '',
                'same_as_links': rec.same_as_links or '',
                'default_image_url': rec.default_image_url or '',
                'available_language_codes': rec.available_language_codes or '',
                'enable_website_schema': self._bool_text(rec.enable_website_schema),
                'enable_search_action': self._bool_text(rec.enable_search_action),
            })
        return rows

    def _export_template_rows(self):
        rows = []
        templates = self.env['midvex.schema.template'].with_context(active_test=False).search([])
        for rec in templates:
            rows.append({
                'name': rec.name or '',
                'schema_type': rec.schema_type or '',
                'description': rec.description or '',
                'json_template': rec.json_template or '',
                'required_fields_json': rec.required_fields_json or '',
                'optional_fields_json': rec.optional_fields_json or '',
                'auto_mapping_json': rec.auto_mapping_json or '',
                'validation_rules_json': rec.validation_rules_json or '',
                'active': self._bool_text(rec.active),
                'sequence': rec.sequence or 0,
                'is_system_template': self._bool_text(rec.is_system_template),
                'load_optional_fields_by_default': self._bool_text(rec.load_optional_fields_by_default),
            })
        return rows

    def _export_mapping_rows(self):
        rows = []
        mappings = self.env['midvex.schema.mapping'].with_context(active_test=False).search([])
        for rec in mappings:
            rows.append({
                'name': rec.name or '',
                'target_model': rec.target_model_id.model or rec.target_model or '',
                'schema_template_name': rec.schema_template_id.name or '',
                'schema_template_type': rec.schema_template_id.schema_type or '',
                'active': self._bool_text(rec.active),
            })
        return rows

    def _export_mapping_line_rows(self):
        rows = []
        lines = self.env['midvex.schema.mapping.line'].search([])
        for rec in lines:
            rows.append({
                'mapping_name': rec.mapping_id.name or '',
                'sequence': rec.sequence or 0,
                'schema_field_path': rec.schema_field_path or '',
                'source_type': rec.source_type or '',
                'token': rec.token or '',
                'odoo_field_name': rec.odoo_field_name or '',
                'default_value': rec.default_value or '',
                'required': self._bool_text(rec.required),
                'field_type': rec.field_type or '',
            })
        return rows

    def _build_datasets(self):
        datasets = []
        if self.include_settings:
            datasets.append(('settings', SETTINGS_COLUMNS, self._export_settings_rows()))
        if self.include_templates:
            datasets.append(('templates', TEMPLATE_COLUMNS, self._export_template_rows()))
        if self.include_mappings:
            datasets.append(('mappings', MAPPING_COLUMNS, self._export_mapping_rows()))
            datasets.append(('mapping_lines', MAPPING_LINE_COLUMNS, self._export_mapping_line_rows()))
        if not datasets:
            raise ValidationError('Select at least one configuration type.')
        return datasets

    def _export_csv_zip(self, datasets):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, columns, rows in datasets:
                text_stream = io.StringIO()
                writer = csv.DictWriter(text_stream, fieldnames=columns, extrasaction='ignore')
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
                archive.writestr('%s.csv' % name, text_stream.getvalue().encode('utf-8-sig'))
        return stream.getvalue()

    def _cell_ref(self, col_idx, row_idx):
        col_idx += 1
        letters = ''
        while col_idx:
            col_idx, remainder = divmod(col_idx - 1, 26)
            letters = chr(65 + remainder) + letters
        return '%s%s' % (letters, row_idx)

    def _sheet_xml(self, columns, rows):
        xml_rows = []
        for row_idx, row in enumerate([dict(zip(columns, columns))] + rows, start=1):
            cells = []
            for col_idx, column in enumerate(columns):
                value = '' if row.get(column) is None else str(row.get(column))
                cells.append(
                    '<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                    % (self._cell_ref(col_idx, row_idx), escape(value))
                )
            xml_rows.append('<row r="%s">%s</row>' % (row_idx, ''.join(cells)))
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>%s</sheetData></worksheet>'
        ) % ''.join(xml_rows)

    def _export_xlsx(self, datasets):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', self._xlsx_content_types(len(datasets)))
            archive.writestr('_rels/.rels', self._xlsx_root_rels())
            archive.writestr('xl/workbook.xml', self._xlsx_workbook(datasets))
            archive.writestr('xl/_rels/workbook.xml.rels', self._xlsx_workbook_rels(len(datasets)))
            for idx, (_name, columns, rows) in enumerate(datasets, start=1):
                archive.writestr('xl/worksheets/sheet%s.xml' % idx, self._sheet_xml(columns, rows))
        return stream.getvalue()

    def _xlsx_content_types(self, count):
        sheets = ''.join(
            '<Override PartName="/xl/worksheets/sheet%s.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            % idx for idx in range(1, count + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '%s</Types>'
        ) % sheets

    def _xlsx_root_rels(self):
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>'
        )

    def _xlsx_workbook(self, datasets):
        sheets = ''.join(
            '<sheet name="%s" sheetId="%s" r:id="rId%s"/>'
            % (escape(name[:31]), idx, idx)
            for idx, (name, _columns, _rows) in enumerate(datasets, start=1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets>%s</sheets></workbook>'
        ) % sheets

    def _xlsx_workbook_rels(self, count):
        rels = ''.join(
            '<Relationship Id="rId%s" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet%s.xml"/>'
            % (idx, idx)
            for idx in range(1, count + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '%s</Relationships>'
        ) % rels

    def action_export(self):
        self.ensure_one()
        datasets = self._build_datasets()
        if self.file_format == 'csv':
            content = self._export_csv_zip(datasets)
            filename = 'midvex_schema_config_csv.zip'
        else:
            content = self._export_xlsx(datasets)
            filename = 'midvex_schema_config.xlsx'
        self.write({
            'export_file': base64.b64encode(content),
            'export_filename': filename,
            'message': 'Export ready. Download the generated file below.',
        })
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import / Export Configs',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    def _read_csv_zip(self, payload):
        datasets = {}
        try:
            with zipfile.ZipFile(io.BytesIO(payload), 'r') as archive:
                for info in archive.infolist():
                    if not info.filename.endswith('.csv'):
                        continue
                    name = info.filename.rsplit('/', 1)[-1][:-4]
                    content = archive.read(info.filename).decode('utf-8-sig')
                    datasets[name] = list(csv.DictReader(io.StringIO(content)))
        except zipfile.BadZipFile as exc:
            raise ValidationError('CSV import expects the ZIP file generated by this wizard.') from exc
        return datasets

    def _read_xlsx(self, payload):
        try:
            archive = zipfile.ZipFile(io.BytesIO(payload), 'r')
        except zipfile.BadZipFile as exc:
            raise ValidationError('The selected file is not a valid .xlsx workbook.') from exc
        with archive:
            shared_strings = self._read_shared_strings(archive)
            workbook = ET.fromstring(archive.read('xl/workbook.xml'))
            rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
            rel_map = {
                rel.attrib['Id']: rel.attrib['Target']
                for rel in rels
            }
            datasets = {}
            for sheet in workbook.findall('.//main:sheet', _NS):
                name = sheet.attrib.get('name')
                rel_id = sheet.attrib.get('{%s}id' % _NS['rel'])
                target = rel_map.get(rel_id, '')
                path = 'xl/%s' % target if not target.startswith('/') else target[1:]
                rows = self._read_sheet_rows(archive.read(path), shared_strings)
                if not rows:
                    datasets[name] = []
                    continue
                columns = rows[0]
                datasets[name] = [
                    {columns[idx]: value for idx, value in enumerate(row) if idx < len(columns)}
                    for row in rows[1:]
                ]
            return datasets

    def _read_shared_strings(self, archive):
        if 'xl/sharedStrings.xml' not in archive.namelist():
            return []
        root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        values = []
        for item in root.findall('.//main:si', _NS):
            text = ''.join(node.text or '' for node in item.findall('.//main:t', _NS))
            values.append(text)
        return values

    def _column_index(self, ref):
        letters = ''.join(ch for ch in ref if ch.isalpha())
        value = 0
        for ch in letters:
            value = value * 26 + ord(ch.upper()) - 64
        return max(value - 1, 0)

    def _read_sheet_rows(self, payload, shared_strings):
        root = ET.fromstring(payload)
        rows = []
        for row_node in root.findall('.//main:row', _NS):
            cells = []
            for cell in row_node.findall('main:c', _NS):
                col_idx = self._column_index(cell.attrib.get('r', 'A1'))
                while len(cells) <= col_idx:
                    cells.append('')
                ctype = cell.attrib.get('t')
                if ctype == 'inlineStr':
                    value = ''.join(node.text or '' for node in cell.findall('.//main:t', _NS))
                else:
                    raw = cell.findtext('main:v', default='', namespaces=_NS)
                    value = shared_strings[int(raw)] if ctype == 's' and raw else raw
                cells[col_idx] = value
            rows.append(cells)
        return rows

    def action_import(self):
        self.ensure_one()
        if not self.import_file:
            raise ValidationError('Choose a file to import.')
        payload = base64.b64decode(self.import_file)
        datasets = self._read_csv_zip(payload) if self.file_format == 'csv' else self._read_xlsx(payload)
        counts = []
        if self.include_settings and 'settings' in datasets:
            counts.append('%s settings' % self._import_settings(datasets['settings']))
        if self.include_templates and 'templates' in datasets:
            counts.append('%s templates' % self._import_templates(datasets['templates']))
        if self.include_mappings and 'mappings' in datasets:
            mapping_count = self._import_mappings(
                datasets['mappings'], datasets.get('mapping_lines', [])
            )
            counts.append('%s mappings' % mapping_count)
        self.write({
            'message': 'Imported %s.' % ', '.join(counts) if counts else 'No matching sheets were found.',
        })
        return self._reopen()

    def _import_settings(self, rows):
        count = 0
        Settings = self.env['midvex.schema.settings']
        for row in rows:
            website = self._resolve_website(row)
            if not website:
                raise ValidationError('Could not resolve website for settings row.')
            company = self._resolve_company(row, website)
            vals = {
                'website_id': website.id,
                'company_id': company.id,
                'enable_global_schema': self._parse_bool(row.get('enable_global_schema')),
                'organization_name': row.get('organization_name') or '',
                'legal_name': row.get('legal_name') or '',
                'alternate_names': row.get('alternate_names') or '',
                'logo_url': row.get('logo_url') or '',
                'website_url': row.get('website_url') or '',
                'email': row.get('email') or '',
                'phone': row.get('phone') or '',
                'street_address': row.get('street_address') or '',
                'city': row.get('city') or '',
                'region': row.get('region') or '',
                'postal_code': row.get('postal_code') or '',
                'country_code': row.get('country_code') or '',
                'same_as_links': row.get('same_as_links') or '',
                'default_image_url': row.get('default_image_url') or '',
                'available_language_codes': row.get('available_language_codes') or '',
                'enable_website_schema': self._parse_bool(row.get('enable_website_schema')),
                'enable_search_action': self._parse_bool(row.get('enable_search_action')),
            }
            existing = Settings.search([('website_id', '=', website.id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                Settings.create(vals)
            count += 1
        return count

    def _import_templates(self, rows):
        count = 0
        Template = self.env['midvex.schema.template'].with_context(active_test=False)
        for row in rows:
            name = (row.get('name') or '').strip()
            schema_type = (row.get('schema_type') or '').strip()
            if not name or not schema_type:
                continue
            vals = {
                'name': name,
                'schema_type': schema_type,
                'description': row.get('description') or '',
                'json_template': row.get('json_template') or '{}',
                'required_fields_json': row.get('required_fields_json') or '[]',
                'optional_fields_json': row.get('optional_fields_json') or '[]',
                'auto_mapping_json': row.get('auto_mapping_json') or '{}',
                'validation_rules_json': row.get('validation_rules_json') or '{}',
                'active': self._parse_bool(row.get('active')),
                'sequence': int(row.get('sequence') or 10),
                'load_optional_fields_by_default': self._parse_bool(
                    row.get('load_optional_fields_by_default')
                ),
            }
            existing = Template.search([
                ('name', '=', name),
                ('schema_type', '=', schema_type),
            ], limit=1)
            if existing:
                existing.write(vals)
            else:
                vals['is_system_template'] = self._parse_bool(row.get('is_system_template'))
                Template.create(vals)
            count += 1
        return count

    def _find_template(self, row):
        name = (row.get('schema_template_name') or '').strip()
        schema_type = (row.get('schema_template_type') or '').strip()
        domain = [('name', '=', name)]
        if schema_type:
            domain.append(('schema_type', '=', schema_type))
        return self.env['midvex.schema.template'].with_context(active_test=False).search(domain, limit=1)

    def _import_mappings(self, mapping_rows, line_rows):
        lines_by_mapping = {}
        for line in line_rows:
            lines_by_mapping.setdefault(line.get('mapping_name'), []).append(line)
        count = 0
        Mapping = self.env['midvex.schema.mapping'].with_context(active_test=False)
        for row in mapping_rows:
            name = (row.get('name') or '').strip()
            model_name = (row.get('target_model') or '').strip()
            if not name or not model_name:
                continue
            model_rec = self.env['ir.model'].search([('model', '=', model_name)], limit=1)
            template = self._find_template(row)
            if not model_rec:
                raise ValidationError('Could not resolve target model "%s".' % model_name)
            if not template:
                raise ValidationError('Could not resolve schema template for mapping "%s".' % name)
            vals = {
                'name': name,
                'target_model_id': model_rec.id,
                'schema_template_id': template.id,
                'active': self._parse_bool(row.get('active')),
            }
            line_commands = [Command.clear()]
            for line in lines_by_mapping.get(name, []):
                schema_field_path = (line.get('schema_field_path') or '').strip()
                if not schema_field_path:
                    continue
                line_commands.append(Command.create({
                    'sequence': int(line.get('sequence') or 10),
                    'schema_field_path': schema_field_path,
                    'source_type': line.get('source_type') or 'token',
                    'token': line.get('token') or '',
                    'odoo_field_name': line.get('odoo_field_name') or '',
                    'default_value': line.get('default_value') or '',
                    'required': self._parse_bool(line.get('required')),
                    'field_type': line.get('field_type') or 'char',
                }))
            vals['line_ids'] = line_commands
            existing = Mapping.search([('name', '=', name)], limit=1)
            if existing:
                existing.write(vals)
            else:
                Mapping.create(vals)
            count += 1
        return count
