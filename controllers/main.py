import json
from odoo import http
from odoo.http import request, Response


class MidvexSchemaController(http.Controller):

    @http.route(
        '/schema-preview/<int:record_id>',
        type='http',
        auth='user',
        website=True,
        csrf=False,
    )
    def schema_preview(self, record_id, **kwargs):
        if not request.env.user.has_group(
            'midvex_schema_manager.group_midvex_schema_manager'
        ):
            return Response('Forbidden', status=403, content_type='text/plain')

        record = request.env['midvex.schema.record'].sudo().browse(record_id)
        if not record.exists() or not record.active:
            return Response('Not Found', status=404, content_type='text/plain')

        # Use build_schema_data() — read-only, no database write
        data = record.build_schema_data()
        output = json.dumps(data, ensure_ascii=False, indent=2) if data else '{}'
        return Response(
            output,
            status=200,
            content_type='application/json; charset=utf-8',
        )
