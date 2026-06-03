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

        if not record.generated_json:
            record.generate_json()

        output = record.generated_json or json.dumps({})
        return Response(
            output,
            status=200,
            content_type='application/json; charset=utf-8',
        )
