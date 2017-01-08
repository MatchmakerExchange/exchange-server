import os
import json
import unittest

from copy import deepcopy
from unittest import TestCase
from random import randint

API_MIME_TYPE = 'application/vnd.ga4gh.matchmaker.v1.0+json'
EXAMPLE_REQUEST = {
    'patient': {
        'id': '1',
        'label': 'patient 1',
        'contact': {
            'name': 'First Last',
            'institution': 'Contact Institution',
            'href': 'mailto:first.last@example.com',
        },
        'ageOfOnset': 'HP:0003577',
        'inheritanceMode': 'HP:0000006',
        'features': [
            {
                'id': 'HP:0001366',  # Canonically: HP:0000252
                'label': 'Microcephaly',
            },
            {
                'id': 'HP:0000522',
                'label': 'Alacrima',
                'ageOfOnset': 'HP:0003593',
            },
        ],
        'genomicFeatures': [{
            "gene": {
              "id": "EFTUD2",
            },
            "type": {
              "id": "SO:0001587",
              "label": "STOPGAIN",
            },
            "variant": {
              "alternateBases": "A",
              "assembly": "GRCh37",
              "end": 42929131,
              "referenceBases": "G",
              "referenceName": "17",
              "start": 42929130,
            },
            "zygosity": 1,
        }],
        'disorders': [{
            "id": "MIM:610536",
        }],
    }
}


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        from mme_server.cli import main

        self.accept_header = ('Accept', API_MIME_TYPE)
        self.content_type_header = ('Content-Type', 'application/json')
        self.headers = [
            self.accept_header,
            self.content_type_header,
        ]

    def test_validate(self):
        from mme_server.server import app

        self.client = app.test_client()
        self.data = json.dumps(EXAMPLE_REQUEST)
        response = self.client.post('/v1/validate/match', data=self.data, headers=self.headers)
        print(str(response.get_data()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-Type'], API_MIME_TYPE)
        response_data = json.loads(response.get_data(as_text=True))
        patient = response_data['patient']
        self.assertEqual(len(patient['genomicFeatures']), 1)
        phenotype = patient['features'][0]
        # Ensure it converted the HPO id from synonym to canonical id
        self.assertEqual(phenotype['id'], 'HP:0000252')
        # Ensure it converted the gene symbol to Ensembl id
        gene = patient['genomicFeatures'][0]['gene']
        self.assertTrue(gene['id'].startswith('ENSG'))
        self.assertTrue(len(gene['label']) > 0)


if __name__ == '__main__':
    unittest.main()
