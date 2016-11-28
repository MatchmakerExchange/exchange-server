# Matchmaker Exchange Reference Server
<!-- [![Build Status](https://api.travis-ci.org/MatchmakerExchange/exchange-server.svg)](https://travis-ci.org/MatchmakerExchange/exchange-server) -->
[![License](https://img.shields.io/github/license/MatchmakerExchange/exchange-server.svg)](LICENSE.txt)
<!-- [![Coverage Status](https://img.shields.io/coveralls/MatchmakerExchange/exchange-server/master.svg)](https://coveralls.io/github/MatchmakerExchange/exchange-server?branch=master) -->

An exchange server (built on top of the [MME Reference Server](https://github.com/MatchmakerExchange/reference-server)) that proxies requests from one MME service to one or more other MME services over the [Matchmaker Exchange API](https://github.com/ga4gh/mme-apis).

## Not yet functional

## Dependencies
- Python 2.7 or 3.3+
- ElasticSearch


## Quickstart

1. Clone the repository:

    ```sh
    git clone https://github.com/MatchmakerExchange/exchange-server.git
    cd exchange-server
    ```

1. Install the Python package dependencies (it's recommended that you do this inside a [Python virtual environment](#install-venv)):

    ```sh
    pip install -r requirements.txt
    ```

1. Start up your elasticsearch server in another shell (see the [ElasticSearch instructions](#install-es) for more information).

    ```sh
    ./path/to/elasticsearch
    ```

1. Download and index vocabularies and sample data:

    ```sh
    mme-server quickstart
    ```

1. Start up exchange server:

    ```sh
    python manage.py
    ```

1. Try it out:

    ```sh
    curl -XPOST -H 'Content-Type: application/vnd.ga4gh.matchmaker.v1.0+json' \
         -H 'Accept: application/vnd.ga4gh.matchmaker.v1.0+json' \
         -d '{"patient":{
        "id":"1",
        "contact": {"name":"Jane Doe", "href":"mailto:jdoe@example.edu"},
        "features":[{"id":"HP:0000522"}],
        "genomicFeatures":[{"gene":{"id":"NGLY1"}}]
      }}' localhost:8000/match
    ```

## Installation

## <a name="install-venv"></a> Your Python environment

It's recommended that you run the server within a Python virtual environment so dependencies are isolated from your system-wide Python installation.

To set up your Python virtual environment:

```sh
# Set up virtual environment within a folder '.virtualenv' (add `-p python3` to force python 3)
virtualenv .virtualenv
```

You can then activate this environment within a particular shell with:

```sh
source .virtualenv/bin/activate
```

### <a name="install-es"></a> ElasticSearch

First, download elasticsearch:

```sh
wget https://download.elasticsearch.org/elasticsearch/release/org/elasticsearch/distribution/tar/elasticsearch/2.1.1/elasticsearch-2.1.1.tar.gz
tar -xzf elasticsearch-2.1.1.tar.gz
```

Then, start up a local elasticsearch cluster to serve as our database (`-Des.path.data=data` puts the elasticsearch indices in a subdirectory called `data`):

```sh
./elasticsearch-2.1.1/bin/elasticsearch -Des.path.data=data
```


## Questions

If you have any questions, feel free to post an issue on GitHub.


## Contributing

This repository is managed by the Matchmaker Exchange technical team. You can reach us via GitHub or by [email](mailto:api@matchmakerexchange.org).

Contributions are most welcome! Post an issue, submit a bugfix, or just try it out. We hope you find it useful.


## Implementations

We don't know of any organizations using this code in a production setting just yet. If you are, please let us know! We'd love to list you here.
