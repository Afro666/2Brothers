"""One bounded real Nemotron health call. Prints safe metadata, never keys or model text."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from agent.model import Nemotron, ModelError, provider_settings


async def check(timeout=20, *, transport=None):
    started = time.monotonic()
    result = {'status': 'ERROR', 'model': 'not-configured', 'endpoint_host': 'not-configured'}
    model = None
    try:
        base, name, key = provider_settings()
        result.update(model=name.replace(key, '[REDACTED]'),
                      endpoint_host=(urlsplit(base).hostname or '').replace(key, '[REDACTED]'))
        model = Nemotron(timeout=timeout, max_attempts=1, transport=transport)
        await asyncio.wait_for(model.ping(), timeout=timeout)
        result.update(status='OK', usage=model.meter.total())
    except (asyncio.TimeoutError, ModelError, ValueError) as exc:
        # Fixed error classes/code only: upstream errors and config can echo secrets.
        result['error'] = type(exc).__name__
        if isinstance(exc, ModelError) and isinstance(exc.status_code, int):
            result['http_status'] = exc.status_code
    finally:
        if model is not None:
            await model.close()
        result['latency_ms'] = round((time.monotonic() - started) * 1000)
    return result


def main():
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / '.env', override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=20)
    args = parser.parse_args()
    if not 0 < args.timeout <= 60:
        parser.error('--timeout must be greater than 0 and at most 60 seconds')
    result = asyncio.run(check(args.timeout))
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'OK' else 1


if __name__ == '__main__':
    raise SystemExit(main())
