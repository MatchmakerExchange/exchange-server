"""
A database manager for exchange server statistics.
"""

from __future__ import with_statement, division, unicode_literals

import json
import logging

from mme_server.managers.base import BaseManager
from mme_server.managers import Managers

logger = logging.getLogger(__name__)


class StatsManager(BaseManager):
    NAME = 'exchange'
    DOC_TYPE = 'request'
    CONFIG = {
        'mappings': {
            'request': {
                'properties': {
                    'sender_id': {
                        'type': 'string',
                        'index': 'not_analyzed',
                    },
                    'receiver_id': {
                        'type': 'string',
                        'index': 'not_analyzed',
                    },
                    'query_patient_id': {
                        'type': 'string',
                        'index': 'not_analyzed',
                    },
                    'is_test': {
                        'type': 'boolean',
                    },
                    'response_patient_ids': {
                        'type': 'string',
                        'index': 'not_analyzed',
                    },
                    'raw_request': {
                        'type': 'string',
                        'index': 'not_analyzed',
                    },
                    'request': {
                        'type': 'string',
                        'index': 'not_analyzed',
                    },
                    'raw_response': {
                        'type': 'string',
                        'index': 'not_analyzed',
                    },
                    'response': {
                        'type': 'string',
                        'index': 'not_analyzed',
                    },
                    'created_at': {
                        'type': 'date',
                    },
                    'status': {
                        'type': 'integer',
                    },
                    'took': {
                        'type': 'float',
                    },
                }
            }
        }
    }


    def get_recent_requests(self, n=10):
        if self.index_exists():
            s = self.search()
            s = s.filter('term', is_test=False)
            s = s.sort('-created_at')
            s = s[:n]
            results = s.execute()
            return results.hits
        else:
            return []

    def save_request(self, request, recipient, response):
        """Store the provided request/response for quality assurance

        request - a MMERequest object
        recipient - a server object for the queried server
        response - a MMEResponse object
        """
        doc = {
            'sender_id': request.get_sender_id(),
            'receiver_id': recipient['server_id'],
            'query_patient_id': request.get_patient_id(),
            'is_test': request.is_test(),
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
            self.save(doc)
        except Exception as e:
            logger.warning('Error logging request: {}'.format(e))


# Register manager
Managers.add_manager('stats', StatsManager)
