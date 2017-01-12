import os

import logging
import json
import flask

from collections import defaultdict
from datetime import datetime
from elasticsearch_dsl import Search
from flask import after_this_request, jsonify, render_template, request as flask_request
from flask_negotiate import consumes, produces
from werkzeug.exceptions import BadRequest

from mme_server.auth import auth_token_required
from mme_server.backend import get_backend
from mme_server.server import app, API_MIME_TYPE
from mme_server.models import MatchRequest, MatchResponse
from mme_server.schemas import validate_request, validate_response, ValidationError

from .compat import urlopen, HTTPError, Request
# Import manager to register
from .managers import StatsManager

VERSION = '0.1'
USER_AGENT = 'mme-exchange-server/{}'.format(VERSION)

logger = logging.getLogger(__name__)

# Default to development configuration
app_settings = os.getenv('APP_SETTINGS', 'config.dev.Config')
app.config.from_object(app_settings)
app.template_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')


class ErrorResponse(Exception):
    """Custom Exception class that wraps an error response"""
    def __init__(self, message, status=500):
        self.message = message
        self.status = status

    def get_response(self):
        data = { 'message': self.message }
        response = jsonify(**data)
        response.status_code = self.status
        return response


class MMERequest:
    def __init__(self, body, sender_id=None, timestamp=None):
        assert body
        self.body = body
        self.sender_id = sender_id
        self.timestamp = datetime.now() if timestamp is None else timestamp
        self.prepared = self._normalize_request(body)

    def is_test(self):
        return bool(self.get_raw().get('patient', {}).get('test'))

    def get_raw(self):
        return self.body

    def get_normalized(self):
        assert self.prepared is not None, 'Request was not normalized'
        return self.prepared

    def get_sender_id(self):
        return self.sender_id

    def get_timestamp(self):
        return self.timestamp

    def get_patient_id(self):
        return self.get_raw().get('patient', {}).get('id', '')

    def get_headers(self, auth_token=None):
        sender_id = self.get_sender_id()
        headers = {
            'User-Agent': USER_AGENT,
            'Content-Type': API_MIME_TYPE,
            'Accept': API_MIME_TYPE,
            # Set the header for the authenticated client id
            'X-Forwarded-For': sender_id,
        }
        if auth_token:
            headers['X-Auth-Token'] = auth_token
            logger.debug('Authenticating with: {}...'.format(auth_token[:4]))

        return  headers

    @classmethod
    def _normalize_request(cls, raw_request):
        logger.info('Normalizing request')
        try:
            normalized = MatchRequest.from_api(raw_request).to_api()
        except Exception as e:
            raise ErrorResponse('Error normalizing request: {}'.format(e), status=400)

        try:
            logger.info('Validate normalized request')
            validate_request(normalized)
        except ValidationError as e:
            raise ErrorResponse('Normalized request does not conform to API specification: {}'.format(e), status=422)

        return normalized

    def send(self, server, timeout=10):
        """Send the request to the given server and return a MMEResponse object

        timeout - terminate the request after this many seconds
        """
        server_id = server['server_id']
        base_url = server['base_url']
        auth_token = server['server_key']

        assert server_id and base_url

        match_url = '{}/match'.format(base_url)

        headers = self.get_headers(auth_token=auth_token)

        logger.info('Opening request to URL: ' + match_url)
        try:
            request = self.get_normalized()

            # Serialize request
            request_data = json.dumps(request).encode('utf-8')

            sent_request_at = datetime.now()
            req = Request(match_url, data=request_data, headers=headers)
            try:
                handler = urlopen(req, timeout=timeout)
                code = handler.getcode()
                response_body = handler
            except HTTPError as e:
                # Handle HTTP Errors thrown for non-200 responses
                code = e.code
                response_body = e

            logger.info('Received HTTP {}'.format(code))
            received_response_at = datetime.now()
            elapsed_time = (received_response_at - sent_request_at).total_seconds()

            logger.info('Loading response')
            response_data = response_body.read().decode('utf-8')
            response = json.loads(response_data)
        except Exception as e:
            logger.error('Request resulted in error: {}'.format(e))
            return MMEResponse(request, {'message': str(e)}, status=500)

        return MMEResponse(request, response, status=code, time=elapsed_time)


class MMEResponse:
    def __init__(self, request, body, status=200, time=0):
        assert request and body
        self.request = request
        self.body = body
        self.status = status
        self.time = time
        self.prepared = self._normalize_response(body, status=status, request=request)

    def get_raw(self):
        return self.body

    def get_normalized(self):
        assert self.prepared is not None, 'Response was not normalized'
        return self.prepared

    def get_status(self):
        return self.status

    def get_time(self):
        return self.time

    def get_patient_ids(self):
        pids = []
        for result in self.get_raw().get('results', []):
            pid = result.get('patient', {}).get('id', '')
            pids.append(pid)
        return pids

    def get_response(self):
        """Get the HTTP response"""
        assert self.prepared is not None, 'Response was not normalized'
        response = jsonify(self.prepared)
        response.status_code = self.status
        return response

    @classmethod
    def _normalize_response(cls, raw_response, status=200, request=None):
        if status != 200:
            # Just use the raw response directly
            return raw_response

        logger.info('Validating response syntax')
        try:
            validate_response(raw_response)
        except ValidationError as e:
            # log and return response anyway
            logger.warning('Response does not conform to API specification:\n{}'.format(e))

        try:
            logger.info('Normalizing response')
            normalized = MatchResponse.from_api(raw_response).to_api()
        except Exception as e:
            # log and return response anyway
            logger.warning('Error normalizing response:\n{}'.format(e))

        try:
            validate_response(normalized)
        except ValidationError as e:
            # log and return response anyway
            logger.warning('Normalized response does not conform to API specification:\n{}'.format(e))

        if request:
            # Inject request data into response
            normalized['_request'] = request

        return normalized


def get_outgoing_server(server_id, required=False):
    """Get outgoing server information, given the id

    required - if true, an ErrorResponse will be raised if the server is not found
    """
    logger.info('Looking up server: {}'.format(server_id))
    backend = get_backend()
    servers = backend.get_manager('servers')
    s = servers.search(doc_type=servers.SERVER_DOC_TYPE)
    s = s.filter('term', server_id=server_id)
    results = s.execute()

    if results.hits:
        return results.hits[0]
    elif required:
        raise ErrorResponse('Bad server id: {}'.format(server_id), status=400)


def get_request(flask_request):
    timestamp = datetime.now()

    sender = flask.g.get('server', defaultdict(lambda: None))
    sender_id = sender['server_id']

    try:
        logger.info('Getting flask request data')
        request_json = flask_request.get_json(force=True)
    except BadRequest:
        raise ErrorResponse('Invalid request JSON', status=400)

    try:
        logger.info('Validate request syntax')
        validate_request(request_json)
    except ValidationError as e:
        raise ErrorResponse('Request does not conform to API specification: {}'.format(e), status=422)

    return MMERequest(request_json, sender_id=sender_id, timestamp=timestamp)


@app.route('/', methods=['GET'])
@produces('text/html')
def index():
    backend = get_backend()
    servers = backend.get_manager('servers')
    incoming_servers = servers.list(direction='in').get('rows', [])
    outgoing_servers = servers.list(direction='out').get('rows', [])
    stats = backend.get_manager('stats')
    recent_requests = stats.get_recent_requests()
    return render_template('index.html',
                           outgoing_servers=outgoing_servers,
                           incoming_servers=incoming_servers,
                           recent_requests=recent_requests)


@app.route('/v1/servers/<server_id>/match', methods=['POST'])
@consumes(API_MIME_TYPE)
@produces(API_MIME_TYPE, 'application/json')
@auth_token_required()
def match_server(server_id):
    """Proxy the match request to server with id <server_id>"""
    @after_this_request
    def add_header(response):
        response.headers['Content-Type'] = API_MIME_TYPE
        return response

    try:
        timeout = int(flask_request.args.get('timeout', 20))

        request = get_request(flask_request)

        server = get_outgoing_server(server_id, required=True)

        response = request.send(server, timeout=timeout)

    except ErrorResponse as error:
        return error.get_response()
    except Exception as error:
        error = ErrorResponse('Unexpected error: {}'.format(error), status=500)
        return error.get_response()

    # Log exchange
    try:
        backend = get_backend()
        stats = backend.get_manager('stats')
        stats.save_request(request, server, response)
    except Exception as e:
        logger.warning('Error logging request: {}'.format(e))

    return response.get_response()


@app.route('/v1/validate/match', methods=['POST'])
@consumes(API_MIME_TYPE, 'application/json')
@produces(API_MIME_TYPE, 'application/json')
def normalize_match_request():
    """Validates and normalizes a match request"""
    @after_this_request
    def add_header(response):
        response.headers['Content-Type'] = API_MIME_TYPE
        return response

    try:
        request = get_request(flask_request)

        normalized = request.get_normalized()

    except ErrorResponse as error:
        return error.get_response()
    except Exception as error:
        error = ErrorResponse('Unexpected error: {}'.format(error), status=500)
        return error.get_response()

    response = jsonify(normalized)
    return response
