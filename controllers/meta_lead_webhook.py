"""
Meta Lead Ads webhook → crm.lead automation (Track F per master TZ v0.8).

Direct Facebook → Odoo. No external middleman. Per-page leadgen subscription.

ROUTES:
    GET  /meta/lead-webhook  — verification handshake (hub.challenge)
    POST /meta/lead-webhook  — leadgen notification

REQUIRED ir.config_parameter (set via UI Settings → Technical → System Parameters):
    meta.lead_webhook.verify_token        — random 32 chars, mirrors Meta subscription
    meta.lead_webhook.app_secret          — Meta App Secret (HMAC verification)
    meta.lead_webhook.page_access_token   — long-lived Page Access Token (Graph API)
    meta.lead_webhook.graph_version       — optional, default v25.0

META BUSINESS MANAGER SETUP (manual, post-deploy):
    1. Webhooks → Add Subscription → Object: Page
    2. Callback URL: https://campscout.eu/meta/lead-webhook
    3. Verify Token: <same value as meta.lead_webhook.verify_token>
    4. Subscribe to: leadgen
    5. Per-Page subscription:
       POST https://graph.facebook.com/{page_id}/subscribed_apps?subscribed_fields=leadgen

FLOW (POST):
    1. Verify X-Hub-Signature-256 HMAC SHA256 against app_secret (constant-time)
    2. For each entry.changes with field=leadgen:
       a. Idempotency check: search crm.lead by description ilike "Meta leadgen_id: {id}"
       b. Fetch lead detail from Graph API
       c. find_or_create res.partner (filter user_ids=False, is_company=False)
       d. Create crm.lead → existing automation 1316 fires:
          coupon code + email + SMS + RODO log + loyalty.card.
    3. Always return 200 OK to prevent Meta retry storms.
"""

import hashlib
import hmac
import json
import logging
import re

import requests
from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

GRAPH_TIMEOUT = 10  # seconds


def _normalize_phone(phone):
    if not phone:
        return ''
    return re.sub(r'[^\d+]', '', phone)


def _verify_signature(raw_body, signature_header, app_secret):
    """Constant-time HMAC SHA256 verification of X-Hub-Signature-256."""
    if not signature_header or not app_secret or not raw_body:
        return False
    if not signature_header.startswith('sha256='):
        return False
    expected = (
        'sha256='
        + hmac.new(
            app_secret.encode('utf-8'),
            raw_body if isinstance(raw_body, bytes) else raw_body.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
    )
    return hmac.compare_digest(expected, signature_header)


def _parse_field_data(field_data):
    """Meta field_data: [{name: 'email', values: ['x@y.com']}, ...] → flat dict."""
    result = {}
    for f in field_data or []:
        name = f.get('name')
        values = f.get('values') or []
        if name and values:
            result[name] = values[0]
    return result


class MetaLeadWebhookController(http.Controller):
    @http.route(
        '/meta/lead-webhook',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def verify(self, **kwargs):
        """Meta webhook subscription verification handshake."""
        # Meta uses dotted query params (hub.mode/hub.verify_token/hub.challenge)
        # which Odoo's kwargs binding sometimes drops — read raw werkzeug args.
        args = request.httprequest.args
        mode = args.get('hub.mode')
        token = args.get('hub.verify_token')
        challenge = args.get('hub.challenge', '')

        expected = (
            request.env['ir.config_parameter']
            .sudo()
            .get_param('meta.lead_webhook.verify_token', '')
        )
        if mode == 'subscribe' and expected and token == expected:
            return Response(challenge, status=200, content_type='text/plain')
        _logger.warning(
            'Meta webhook verification failed: mode=%s token_match=%s',
            mode,
            token == expected if expected else 'no_token_configured',
        )
        return Response('Forbidden', status=403)

    @http.route(
        '/meta/lead-webhook',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def handle_leadgen(self):
        """Process Meta leadgen notification(s) and create crm.lead records."""
        Param = request.env['ir.config_parameter'].sudo()
        app_secret = Param.get_param('meta.lead_webhook.app_secret', '')
        page_token = Param.get_param('meta.lead_webhook.page_access_token', '')
        graph_version = Param.get_param('meta.lead_webhook.graph_version', 'v25.0')

        raw = request.httprequest.data
        signature = request.httprequest.headers.get('X-Hub-Signature-256', '')

        if not _verify_signature(raw, signature, app_secret):
            _logger.warning(
                'Meta webhook: invalid X-Hub-Signature-256 from %s',
                request.httprequest.remote_addr,
            )
            return Response('Invalid signature', status=403)

        try:
            payload = json.loads(raw or b'{}')
        except (ValueError, TypeError):
            _logger.warning('Meta webhook: malformed JSON — ack 200 to prevent retry')
            return Response('OK', status=200)

        results = []
        for entry in payload.get('entry') or []:
            for change in entry.get('changes') or []:
                if change.get('field') != 'leadgen':
                    continue
                value = change.get('value') or {}
                leadgen_id = value.get('leadgen_id')
                if not leadgen_id:
                    continue
                try:
                    # savepoint: один payload може містити КІЛЬКА entry/change.
                    # Без savepoint виняток посеред _process_leadgen (напр. після
                    # Partner.create, до Lead.create) лишає курсор Postgres
                    # в "aborted transaction" — усі НАСТУПНІ entry в цьому ж
                    # запиті тихо провалюються тим самим винятком, навіть якщо
                    # самі по собі валідні (той самий клас бага, що в
                    # sendpulse-вебхуці, controllers/main.py). Rollback to
                    # savepoint скидає тільки цей entry, решта йде далі.
                    with request.env.cr.savepoint():
                        result = self._process_leadgen(
                            leadgen_id=leadgen_id,
                            form_id=value.get('form_id'),
                            page_id=value.get('page_id'),
                            created_time=value.get('created_time'),
                            page_token=page_token,
                            graph_version=graph_version,
                        )
                    results.append({'leadgen_id': leadgen_id, **result})
                except Exception as e:
                    _logger.exception('Meta webhook: failed leadgen_id=%s', leadgen_id)
                    results.append(
                        {'leadgen_id': leadgen_id, 'status': 'exception', 'error': str(e)}
                    )

        if results:
            _logger.info('Meta webhook results: %s', results)
        return Response('OK', status=200)

    def _process_leadgen(
        self, leadgen_id, form_id, page_id, created_time, page_token, graph_version
    ):
        # Idempotency — Meta retries on 5xx; check before fetching to save Graph quota
        Lead = request.env['crm.lead'].sudo()
        if Lead.search_count([('description', 'ilike', f'Meta leadgen_id: {leadgen_id}')]):
            return {'status': 'idempotent_skip'}

        # Fetch lead detail from Graph API
        url = f'https://graph.facebook.com/{graph_version}/{leadgen_id}'
        try:
            r = requests.get(
                url,
                params={
                    'access_token': page_token,
                    'fields': 'id,form_id,field_data,created_time',
                },
                timeout=GRAPH_TIMEOUT,
            )
            r.raise_for_status()
            graph_data = r.json()
        except requests.RequestException as e:
            _logger.error('Meta Graph fetch failed for %s: %s', leadgen_id, e)
            return {'status': 'graph_error', 'error': str(e)}

        if graph_data.get('error'):
            _logger.error('Meta Graph error for %s: %s', leadgen_id, graph_data['error'])
            return {'status': 'graph_error', 'error': graph_data['error']}

        fields = _parse_field_data(graph_data.get('field_data'))
        email = fields.get('email') or fields.get('email_address') or ''
        full_name = fields.get('full_name') or fields.get('name') or ''
        phone = _normalize_phone(fields.get('phone_number') or fields.get('phone') or '')
        wiek = (
            fields.get('wiek_dziecka')
            or fields.get('ile_lat_ma_dziecko?')
            or fields.get('age')
            or ''
        )
        miasto = fields.get('miasto') or fields.get('city') or fields.get('miasto?') or ''
        oboz = (
            fields.get('oboz')
            or fields.get('oboz_ktory_cie_interesuje?')
            or fields.get('camp')
            or ''
        )

        if not email and not phone:
            return {'status': 'no_contact'}

        # find_or_create external partner
        Partner = request.env['res.partner'].sudo()
        partner = Partner.browse([])
        if email:
            partner = Partner.search(
                [
                    ('email', '=ilike', email),
                    ('user_ids', '=', False),
                    ('is_company', '=', False),
                ],
                limit=1,
            )
        if not partner:
            country_pl = request.env['res.country'].sudo().search([('code', '=', 'PL')], limit=1)
            partner = Partner.create(
                {
                    'name': full_name or email or phone,
                    'email': email or False,
                    'phone': phone or False,
                    'lang': 'pl_PL',
                    'is_company': False,
                    'country_id': country_pl.id if country_pl else False,
                }
            )

        # RODO journal — write BEFORE crm.lead.create per TZ §F.3.
        # Source = "meta_lead_form" (not "admin_manual"), exact_user_response =
        # verbatim Meta Graph payload, consent_timestamp = Meta created_time.
        Log = request.env['sendpulse.privacy.consent.log'].sudo()
        verbatim = json.dumps(graph_data, ensure_ascii=False)
        for ch, purp in (('email', 'marketing_email'), ('sms', 'marketing_sms')):
            if ch == 'email' and not email:
                continue
            if ch == 'sms' and not phone:
                continue
            Log.create(
                {
                    'email': email or '',
                    'phone': phone or '',
                    'display_name': full_name or '',
                    'purpose': purp,
                    'channel': ch,
                    'legal_basis': 'consent',
                    'policy_version': 'v1.0',
                    'source': 'meta_lead_form',
                    'consent_given': True,
                    'consent_timestamp': created_time or False,
                    'exact_user_response': verbatim,
                    'notes': f'Meta Lead Ads (PL) leadgen_id={leadgen_id} form_id={form_id}',
                }
            )

        # source_id — find or create utm.source for Meta Lead Ads PL 2026
        Source = request.env['utm.source'].sudo()
        source_name = 'Meta Lead Ads — Leads PL 2026'
        source = Source.search([('name', '=', source_name)], limit=1)
        if not source:
            source = Source.create({'name': source_name})

        description = '\n'.join(
            [
                'Źródło: Meta Lead Ads (PL)',
                f'Meta leadgen_id: {leadgen_id}',
                f'Meta form_id: {form_id}' if form_id else '',
                f'Meta page_id: {page_id}' if page_id else '',
                f'Meta created_time: {created_time}' if created_time else '',
                f'Obóz: {oboz}' if oboz else '',
                f'Wiek dziecka: {wiek}' if wiek else '',
                f'Miasto: {miasto}' if miasto else '',
            ]
        )
        # Drop empty lines
        description = '\n'.join(line for line in description.split('\n') if line.strip())

        lead = Lead.create(
            {
                'name': f'Meta Lead PL: {full_name or email}',
                'contact_name': full_name or '',
                'phone': phone or False,
                'email_from': email or False,
                'description': description,
                'type': 'lead',
                'partner_id': partner.id,
                'source_id': source.id,
            }
        )
        return {'status': 'created', 'crm_lead_id': lead.id}
