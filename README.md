# Matchmaker Exchange Reference Server
<!-- [![Build Status](https://api.travis-ci.org/MatchmakerExchange/exchange-server.svg)](https://travis-ci.org/MatchmakerExchange/exchange-server) -->
[![License](https://img.shields.io/github/license/MatchmakerExchange/exchange-server.svg)](LICENSE.txt)
<!-- [![Coverage Status](https://img.shields.io/coveralls/MatchmakerExchange/exchange-server/master.svg)](https://coveralls.io/github/MatchmakerExchange/exchange-server?branch=master) -->

An exchange server (built on top of the [MME Reference Server](https://github.com/MatchmakerExchange/reference-server)) that proxies requests from one MME service to one or more other MME services over the [Matchmaker Exchange API](https://github.com/ga4gh/mme-apis).


## Dependencies

- Python 2.7 or 3.3+
- ElasticSearch 1.7 (to match Travis-CI)


## Quickstart

1. Set up your Python environment and elasticsearch database, according to the instructions for the [reference-server](https://github.com/MatchmakerExchange/reference-server).

1. Clone the repository:

    ```sh
    git clone https://github.com/MatchmakerExchange/exchange-server.git
    cd exchange-server
    ```

1. Install the Python package dependencies:

    ```sh
    pip install -r requirements.txt
    ```

1. Authenticate a server to receive proxied requests:

    ```sh
    mme-server auth add phenomecentral out  --label "PhenomeCentral" --base-url "https://phenomecentral.org/rest/remoteMatcher" --key <PC_AUTH_TOKEN>
    ```

1. Authenticate a client to send proxied requests:

    ```sh
    mme-server auth add client_server in  --label "My Client" --key "<CLIENT_AUTH_TOKEN>"
    ```

1. Start up exchange server:

    ```sh
    python manage.py
    ```

1. Try it out:

    ```sh
    curl -XPOST \
      -H 'X-Auth-Token: <CLIENT_AUTH_TOKEN>' \
      -H 'Content-Type: application/vnd.ga4gh.matchmaker.v1.0+json' \
      -H 'Accept: application/vnd.ga4gh.matchmaker.v1.0+json' \
      -d '{"patient":{
        "id":"1",
        "contact": {"name":"Jane Doe", "href":"mailto:jdoe@example.edu"},
        "features":[{"id":"HP:0000522"}],
        "genomicFeatures":[{"gene":{"id":"NGLY1"}}],
        "test": true
      }}' localhost:8000/v1/servers/phenomecentral/match
    ```


## Questions

If you have any questions, feel free to post an issue on GitHub.


## Contributing

This repository is managed by the Matchmaker Exchange technical team. You can reach us via GitHub or by [email](mailto:api@matchmakerexchange.org).

Contributions are most welcome! Post an issue, submit a bugfix, or just try it out. We hope you find it useful.


## Implementations

We don't know of any organizations using this code in a production setting just yet. If you are, please let us know! We'd love to list you here.
