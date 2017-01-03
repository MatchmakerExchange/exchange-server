import os

import logging
import json
import flask

from datetime import datetime
from elasticsearch_dsl import Search
from flask import after_this_request, jsonify, render_template, request as flask_request
from flask_negotiate import consumes, produces
from werkzeug.exceptions import BadRequest

from mme_server.auth import auth_token_required, get_server_manager
from mme_server.server import app, API_MIME_TYPE, get_backend
from mme_server.models import MatchRequest, MatchResponse
from mme_server.schemas import validate_request, validate_response, ValidationError

from .compat import urlopen, HTTPError, Request

VERSION = '0.1'
USER_AGENT = 'mme-exchange-server/{}'.format(VERSION)
ES_INDEX = 'exchange'
ES_LOG_TYPE = 'request'

logging.basicConfig(level='INFO')
logger = logging.getLogger(__name__)

# Default to development configuration
app_settings = os.getenv('APP_SETTINGS', 'config.dev.Config')
app.config.from_object(app_settings)
app.template_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')


class ErrorResponse(Exception):
    """Custom Exception class that wraps an error response"""
    def __init__(self, response):
        self.response = response


class MMERequest:
    def __init__(self, body, sender_id=None, timeout=10, timestamp=None):
        assert body and timeout > 0
        self.body = body
        self.sender_id = sender_id
        self.timeout = timeout
        self.timestamp = datetime.now() if timestamp is None else timestamp

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

    def normalize(self):
        """Normalize the request"""
        normalized = self._normalize(self.body)
        # Inject server data in request
        sender_id = self.get_sender_id()
        if sender_id:
            normalized['_server'] = {
                'server_id': sender_id
            }

        self.prepared = normalized

    @classmethod
    def _normalize(cls, raw_request):
        logger.info('Normalizing request')
        try:
            normalized = MatchRequest.from_api(raw_request).to_api()
        except Exception as e:
            error = jsonify(message='Error normalizing request: {}'.format(e))
            error.status_code = 400
            raise ErrorResponse(error)

        try:
            logger.info('Validate normalized request')
            validate_request(normalized)
        except ValidationError as e:
            error = jsonify(message='Normalized request does not conform to API specification')
            error.status_code = 422
            raise ErrorResponse(error)

        return normalized

    def send(self, server, timeout=10):
        """Send the request to the given server and return a MMEResponse object

        timeout - terminate the request after this many seconds
        """
        server_id = server['server_id']
        base_url = server['base_url']
        auth_token = server['server_key']
        request = self.get_normalized()

        assert server_id and base_url and base_url.startswith('https://') and request

        match_url = '{}/match'.format(base_url)
        headers = {
            'User-Agent': USER_AGENT,
            'Content-Type': API_MIME_TYPE,
            'Accept': API_MIME_TYPE,
        }

        # Serialize request
        request_data = json.dumps(request).encode('utf-8')

        if auth_token:
            headers['X-Auth-Token'] = auth_token
            logger.info('Authenticating with: {}...'.format(auth_token[:4]))

        logger.info('Opening request to URL: ' + match_url)
        logger.info('Sending request: ' + request_data.decode())
        try:
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

        # Inject server information
        response['_server'] = {
            'id': server_id,
            'baseUrl': base_url,
        }

        return MMEResponse(request, response, status=code, time=elapsed_time)


class MMEResponse:
    def __init__(self, request, body, status=200, time=0):
        assert request and body
        self.request = request
        self.body = body
        self.status = status
        self.time = time
        self.prepared = None

    def normalize(self):
        """Normalize the response"""
        if self.status == 200:
            normalized = self._normalize(self.body)

            # Inject request data into response
            normalized['_request'] = self.request
        else:
            # Just use the raw response directly
            normalized = self.body

        self.prepared = normalized

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
    def _normalize(cls, raw_response):
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

        return normalized


def get_outgoing_servers():
    """Get a list of outgoing servers"""
    servers = get_server_manager()
    response = servers.list()
    servers = []
    for server in response.get('rows', []):
        if server.get('direction') == 'out':
            servers.append(server)

    return servers


def get_outgoing_server(server_id, required=False):
    """Get outgoing server information, given the id

    required - if true, an ErrorResponse will be raised if the server is not found
    """
    logger.info('Looking up server: {}'.format(server_id))
    servers = get_server_manager()
    s = servers.index.search()
    s = s.filter('term', server_id=server_id)
    s = s.filter('term', direction='out')
    results = s.execute()

    if results.hits:
        return results.hits[0]
    elif required:
        error = jsonify(message='Bad server id: {}'.format(server_id))
        error.status_code = 400
        raise ErrorResponse(error)


def get_recent_requests(n=10):
    db = get_backend()
    if db._db.indices.exists(index=ES_INDEX):
        s = Search(using=db._db, index=ES_INDEX, doc_type=ES_LOG_TYPE)
        s = s.sort('-created_at')
        s = s[:n]
        results = s.execute()
        return results.hits
    else:
        return []


def get_request(flask_request):
    timeout = int(flask_request.args.get('timeout', 10))

    timestamp = datetime.now()

    sender_id = flask.g.get('server')['server_id']

    try:
        logger.info('Getting flask request data')
        request_json = flask_request.get_json(force=True)
    except BadRequest:
        error = jsonify(message='Invalid request JSON')
        error.status_code = 400
        raise ErrorResponse(error)

    try:
        logger.info('Validate request syntax')
        validate_request(request_json)
    except ValidationError as e:
        error = jsonify(message='Request does not conform to API specification')
        error.status_code = 422
        raise ErrorResponse(error)

    return MMERequest(request_json, sender_id=sender_id, timeout=timeout, timestamp=timestamp)


def log_request(request, recipient, response):
    """Store the provided request/response for quality assurance

    request - a MMERequest object
    recipient - a server object for the queried server
    response - a MMEResponse object
    """
    db = get_backend()
    doc = {
        'sender_id': request.get_sender_id(),
        'receiver_id': recipient['server_id'],
        'query_patient_id': request.get_patient_id(),
        'response_patient_ids': response.get_patient_ids(),
        'raw_request': json.dumps(request.get_raw()),
        'request': json.dumps(request.get_normalized()),
        'raw_response': json.dumps(response.get_raw()),
        'response': json.dumps(response.get_normalized()),
        'created_at': request.get_timestamp(),
        'status': response.get_status(),
        'took': response.get_time(),
    }
    try:
        db._db.index(index=ES_INDEX, doc_type=ES_LOG_TYPE, body=doc)
    except Exception as e:
        logger.warning('Error logging request: {}'.format(e))


@app.route('/', methods=['GET'])
@produces('text/html')
def index():
    servers = get_outgoing_servers()
    recent_requests = get_recent_requests()
    return render_template('index.html', servers=servers, recent_requests=recent_requests)


@app.route('/v1/servers/<server_id>/match', methods=['POST'])
@consumes(API_MIME_TYPE, 'application/json')
@produces(API_MIME_TYPE)
@auth_token_required()
def match_server(server_id):
    """Proxy the match request to server with id <server_id>"""
    @after_this_request
    def add_header(response):
        response.headers['Content-Type'] = API_MIME_TYPE
        return response

    try:
        request = get_request(flask_request)

        # Validate the email server only after validating the request
        server = get_outgoing_server(server_id, required=True)

        request.normalize()
    except ErrorResponse as error:
        return error.response
    except Exception as error:
        error = jsonify(message='Unexpected error: {}'.format(error))
        error.status_code = 500
        return error

    # Send request
    logger.info('Proxying request to {}'.format(server_id))
    response = request.send(server)

    response.normalize()

    # Log exchange
    try:
        log_request(request, server, response)
    except Exception as e:
        logger.warning('Error logging request: {}'.format(e))

    return response.get_response()

