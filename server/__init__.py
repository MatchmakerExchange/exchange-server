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


def get_outgoing_servers():
    """Get a list of outgoing servers"""
    servers = get_server_manager()
    response = servers.list()
    servers = []
    for server in response.get('rows', []):
        if server.get('direction') == 'out':
            servers.append(server)

    return servers


def get_outgoing_server(server_id):
    """Get a list of outgoing servers"""
    servers = get_server_manager()
    s = servers.index.search()
    s = s.filter('term', server_id=server_id)
    s = s.filter('term', direction='out')
    results = s.execute()

    if results.hits:
        return results.hits[0]


def get_recent_requests(n=10):
    db = get_backend()
    s = Search(using=db._db, index=ES_INDEX, doc_type=ES_LOG_TYPE)
    s = s.sort('-created_at')
    s = s[:n]
    results = s.execute()
    return results.hits


def log_request(sender_id, raw_request, request, receiver_id, response_code, raw_response, response, request_at, response_time):
    """Store the provided request/response for quality assurance

    sender_id - the sending server id
    request - a dictionary of the MME request
    reciever_id - the receiving server id
    response - a dictionary of the MME response
    """
    db = get_backend()
    query_patient_id = request.get('patient', {}).get('id', '')
    response_patient_ids = []
    for result in response.get('results', []):
        pid = result.get('patient', {}).get('id', '')
        response_patient_ids.append(pid)

    now = datetime.now().isoformat()
    doc = {
        'sender_id': sender_id,
        'receiver_id': receiver_id,
        'query_patient_id': query_patient_id,
        'response_patient_ids': response_patient_ids,
        'request': json.dumps(request),
        'response': json.dumps(response),
        'created_at': request_at,
        'status': response_code,
        'took': response_time,
    }
    try:
        db._db.index(index=ES_INDEX, doc_type=ES_LOG_TYPE, body=doc)
    except Exception as e:
        logger.warning('Error logging request: {}'.format(e))


def send_request(server_id, request, timeout):
    """Send the request to the given server and return a tuple (status, response, elapsed_time)

    Elapsed time is in decimal seconds
    Raises TimeoutError if the request takes longer than timeout seconds
    Status of 0 is returned if an error occured processing the request
    """
    headers = {
        'User-Agent': USER_AGENT,
        'Content-Type': API_MIME_TYPE,
        'Accept': API_MIME_TYPE,
    }
    code = 0
    response = {}
    elapsed_time = 0

    # Serialize request
    request_data = json.dumps(request).encode('utf-8')

    server = get_outgoing_server(server_id)
    if not server:
        error = 'Unable to find server: {}'.format(server_id)
        logger.error(error)
        return (code, { 'message': error }, elapsed_time)

    auth_token = server['server_key']
    if auth_token:
        headers['X-Auth-Token'] = auth_token
        logger.info('Authenticating with: {}...'.format(auth_token[:4]))

    base_url = server['base_url']
    assert base_url.startswith('https://')
    match_url = '{}/match'.format(base_url)

    logger.info("Opening request to URL: " + match_url)
    logger.info("Sending request: " + request_data.decode())
    try:
        sent_request_at = datetime.now()
        req = Request(match_url, data=request_data, headers=headers)
        try:
            handler = urlopen(req, timeout=timeout)
            code = handler.getcode()
            response_body = handler
        except HTTPError as e:
            code = e.code
            response_body = e

        logger.info('Received HTTP {}'.format(code))
        received_response_at = datetime.now()
        elapsed_time = (received_response_at - sent_request_at).total_seconds()

        logger.info("Loading response")
        response_data = response_body.read().decode('utf-8')
        response = json.loads(response_data)
    except Exception as e:
        logger.error('Request resulted in error: {}'.format(e))
        return (code, { 'message': str(e) }, elapsed_time)

    # Inject server information
    response['_server'] = {
        'id': server_id,
        'baseUrl': base_url,
    }

    return (code, response, elapsed_time)


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
    """Proxy the match request to server <server>"""

    @after_this_request
    def add_header(response):
        response.headers['Content-Type'] = API_MIME_TYPE
        return response

    timeout = int(flask_request.args.get('timeout', 10))
    received_request_at = datetime.now()

    try:
        logger.info("Getting flask request data")
        request_json = flask_request.get_json(force=True)
    except BadRequest:
        error = jsonify(message='Invalid request JSON')
        error.status_code = 400
        return error

    try:
        logger.info("Validate request syntax")
        validate_request(request_json)
    except ValidationError as e:
        error = jsonify(message='Request does not conform to API specification',
                        request=request_json)
        error.status_code = 422
        return error

    logger.info("Parsing query")
    request = MatchRequest.from_api(request_json).to_api()

    # Set server data in request
    request['_server'] = {
        'server_id': flask.g.get('server')['server_id']
    }

    try:
        validate_request(request)
    except ValidationError as e:
        error = jsonify(message='Normalized request does not conform to API specification')
        error.status_code = 422
        return error

    logger.info("Proxying request to {}".format(server_id))
    response_code, response_json, response_duration = send_request(server_id, request, timeout)
    # Set error code for exchange server errors
    if response_code == 0:
        response_code = 500

    # Inject request data into response
    response_json['_request'] = request

    response = {}
    if response_code == 200:
        logger.info("Validating response syntax")
        try:
            validate_response(response_json)
        except ValidationError as e:
            # log to console and return response anyway
            logger.warning('Response does not conform to API specification:\n{}'.format(e))

        try:
            logger.info("Normalizing response")
            response = MatchResponse.from_api(response_json).to_api()
        except:
            # log to console and return raw response
            logger.warning('Error normalizing response:\n{}'.format(e))

    sender_id = flask.g.get('server')['server_id']
    log_request(sender_id, request_json, request, server_id, response_code, response_json, response, received_request_at, response_duration)

    # Pass through response code
    result = jsonify(response)
    result.status_code = response_code
    return result
