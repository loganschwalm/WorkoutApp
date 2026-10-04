"""The server's modules, loaded into the suite's own process, for the suites that check its functions directly (the cryptography, the
account rules, the state's table) instead of through the API."""

import importlib
import os
import sys
import types

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'backend')
# In the order they depend on one another.
MODULES = ['config', 'validation', 'database', 'state', 'workouts', 'accounts', 'webpush_crypto', 'webpush', 'admin', 'api_routes', 'api_accounts', 'api_data',
           'api_push', 'webserver']


def load_server():
    """Fresh copies of the backend's modules, with everything they define in one namespace (server.ec_multiply, server.STATE_PARTS,
    server.new_username), so a suite can change one (add a part to STATE_PARTS) without it being there for the next. Fresh because
    the modules are cached, and a suite that changed a table would leave it changed."""
    for name in MODULES + ['server']:
        sys.modules.pop(name, None)
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    namespace = types.SimpleNamespace()
    for name in MODULES:
        for key, value in vars(importlib.import_module(name)).items():
            if not key.startswith('__'):
                setattr(namespace, key, value)
    return namespace
