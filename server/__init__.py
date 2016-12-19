import os

import logging
import json

from flask import after_this_request, g, jsonify, render_template, request
from flask_negotiate import consumes, produces
from werkzeug.exceptions import BadRequest

from mme_server.decorators import auth_token_required
from mme_server.server import app, API_MIME_TYPE, get_backend
from mme_server.models import MatchRequest, MatchResponse
from mme_server.schemas import validate_request, validate_response, ValidationError

from .compat import urlopen, Request

logger = logging.getLogger(__name__)

# Default to development configuration
app_settings = os.getenv('APP_SETTINGS', 'config.dev.Config')
app.config.from_object(app_settings)
app.template_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')

def get_connected_servers():
    db = get_backend()
    response = db.servers.list()
    servers = {}
    for server in response.get('rows', []):
        if server.get('direction') == 'out':
            server_id = server['server_id']
            servers[server_id] = server

    return servers


def send_request(server, request_data, timeout):
    base_url = server['base_url']
    assert base_url.startswith('https://')

    url = '{}/match'.format(base_url)
    headers = {
        'User-Agent': 'mme-server/0.2',
        'Content-Type': API_MIME_TYPE,
        'Accept': API_MIME_TYPE,
    }

    auth_token = server.get('server_key')
    if auth_token:
        headers['X-Auth-Token'] = auth_token

    print("Opening request to URL: " + url)
    print("Sending request: " + request_data.decode())
    req = Request(url, data=request_data, headers=headers)
    handler = urlopen(req)

    print("Loading response")
    response = handler.read().decode('utf-8')
    response_json = json.loads(response)

    logger.info("Validating response syntax")
    try:
        validate_response(response_json)
    except ValidationError as e:
        # log to console and return response anyway
        logger.error('Response does not conform to API specification:\n{}'.format(e))

    try:
        logger.info("Normalizing response")
        response_obj = MatchResponse.from_api(response_json)
        response_api = response_obj.to_api()
    except:
        # log to console and return raw response
        logger.error('Error normalizing response:\n{}'.format(e))
        response_api = response_json

    # Inject server information
    response_api['_server'] = {
        'id': server.get('server_id'),
        'baseUrl': server.get('base_url')
    }
    return response_api


def proxy_request(request_data, timeout=5, server_ids=None):
    from multiprocessing import Pool

    db = get_backend()
    all_servers = db.servers.list().get('rows', [])

    servers = []
    for server in all_servers:
        if (server.get('direction') == 'out' and
            (not server_ids or server['server_id'] in server_ids)):
            servers.append(server)

    handles = []
    if servers:
        pool = Pool(processes=4)

        for server in servers:
            handle = pool.apply_async(send_request, (server, request_data, timeout))
            handles.append((server, handle))

    results = []
    for server, handle in handles:
        try:
            result = handle.get(timeout=timeout)
        except TimeoutError:
            print('Timed out')
            result = None
        except Exception as e:
            print('Other error: {}'.format(e))
            continue

        results.append((server, result))
    return results


@app.route('/', methods=['GET'])
@produces('text/html')
def index():
    servers = get_connected_servers()
    return render_template('index.html', servers=servers)


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

    timeout = int(request.args.get('timeout', 10))

    try:
        logger.info("Getting flask request data")
        request_json = request.get_json(force=True)
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
    request_obj = MatchRequest.from_api(request_json).to_api()

    # Inject server data into request
    request_server = g.get('server')
    if request_server:
        request_obj['_server'] = {
            'server_id': request_server['server_id']
        }

    try:
        validate_request(request_obj)
    except ValidationError as e:
        error = jsonify(message='Created request does not conform to API specification')
        print(request_obj)
        error.status_code = 422
        return error

    logger.info("Preparing request to proxy")
    request_data = json.dumps(request_obj).encode('utf-8')

    logger.info("Proxying request")
    logger.info(json.dumps(request_obj, indent=4))
    server_responses = proxy_request(request_data, timeout=timeout, server_ids=[server_id])

    server, response = server_responses[0]
    # Inject request data into response
    response['request'] = request_obj

    return jsonify(response)
