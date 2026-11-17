"""Explicit operator control; configuration is never presented as live reachability."""
import os


def model_enabled(environ=None):
    environ = os.environ if environ is None else environ
    return str(environ.get('NEMOTRON_ENABLED', 'true')).strip().lower() in ('true', '1', 'on')


def capabilities(environ=None):
    environ = os.environ if environ is None else environ
    return {'model_enabled': model_enabled(environ),
            'model_configured': model_enabled(environ) and bool(environ.get('VERDA_INFERENCE_KEY', '').strip()),
            'model_reachable': None}  # No model probe or paid generation in liveness.
