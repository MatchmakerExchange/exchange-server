#!/usr/bin/env python
from __future__ import with_statement, division, unicode_literals

import logging
import os
import sys
import unittest

from server import app


__package__ = 'server'
DEFAULT_HOST = '0.0.0.0'
DEFAULT_PORT = 8000


def run_tests():
    suite = unittest.TestLoader().discover('.'.join([__package__, 'tests']))
    unittest.TextTestRunner().run(suite)


def parse_args(args):
    from argparse import ArgumentParser

    parser = ArgumentParser()
    subparsers = parser.add_subparsers(title='subcommands')
    subparser = subparsers.add_parser('start', description="Start running a simple Matchmaker Exchange API server")
    subparser.add_argument("-p", "--port", default=DEFAULT_PORT,
                           dest="port", type=int, metavar="PORT",
                           help="The port the server will listen on (default: %(default)s)")
    subparser.add_argument("--host", default=DEFAULT_HOST,
                           dest="host", metavar="IP",
                           help="The host the server will listen to (0.0.0.0 to listen globally; 127.0.0.1 to listen locally; default: %(default)s)")
    subparser.set_defaults(function=app.run)

    subparser = subparsers.add_parser('test', description="Run tests")
    subparser.set_defaults(function=run_tests)

    args = parser.parse_args(args)
    if not hasattr(args, 'function'):
        parser.error('a subcommand must be specified')
    return args


def main(args=sys.argv[1:]):
    logging.basicConfig(level='INFO')
    args = parse_args(args)

    # Call the function for the corresponding subparser
    kwargs = vars(args)
    function = kwargs.pop('function')
    function(**kwargs)


if __name__ == '__main__':
    sys.exit(main())
