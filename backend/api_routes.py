"""What each API request is answered by.

ROUTES maps (method, path) to the name of the AppHandler method that answers it and whether it is for anyone: a request that is not
needs a signed-in account (401 otherwise), and a request no route has is answered 404, only once it is known who asks.
A path that carries an id (PUT /api/workouts/12) is a PREFIXED route. To add an endpoint, write its method in one of the api_*.py
mixins and add its line here; tests/suites/api.py checks that every route is answered, and that none is open without meaning to be.
"""

ROUTES = {
    ('GET', '/api/auth/me'): ('auth_me', True),
    ('POST', '/api/auth/register'): ('register', True),
    ('POST', '/api/auth/login'): ('sign_in', True),
    ('POST', '/api/auth/forgot-password'): ('send_reset_code', True),
    ('POST', '/api/auth/reset-password'): ('reset_password', True),
    ('POST', '/api/auth/logout'): ('sign_out', True),
    ('POST', '/api/account/email'): ('change_email', False),
    ('POST', '/api/account/password'): ('change_password', False),
    ('POST', '/api/account/delete'): ('delete_account', False),
    ('GET', '/api/workouts'): ('list_workouts', False),
    ('POST', '/api/workouts'): ('create_workout', False),
    ('GET', '/api/active-session'): ('get_active_session', False),
    ('POST', '/api/active-session'): ('save_active_session', False),
    ('DELETE', '/api/active-session'): ('clear_active_session', False),
    ('GET', '/api/state'): ('get_state', False),
    ('PUT', '/api/state'): ('replace_state', False),
    ('PATCH', '/api/state'): ('patch_state', False),
    ('GET', '/api/export'): ('export_json', False),
    ('GET', '/api/export.csv'): ('export_csv', False),
    ('POST', '/api/import'): ('import_account', False),
    ('GET', '/api/push/key'): ('push_key', False),
    ('POST', '/api/push/subscribe'): ('push_subscribe', False),
    ('POST', '/api/push/unsubscribe'): ('push_unsubscribe', False),
    ('POST', '/api/push/test'): ('push_test', False),
}

PREFIXED = (
    ('PUT', '/api/workouts/', 'update_workout'),
    ('DELETE', '/api/workouts/', 'delete_workout'),
)


def find_route(method, path):
    """(the method of AppHandler that answers it, whether it is for anyone), or (None, False) for a request nothing answers."""
    if (method, path) in ROUTES:
        return ROUTES[(method, path)]
    for prefixed_method, prefix, handler in PREFIXED:
        if method == prefixed_method and path.startswith(prefix):
            return handler, False
    return None, False
