"""One entry point; resolve every component relative to this distribution."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
for folder in ('backend/context_compression', 'backend/research_pipeline'):
    sys.path.insert(0, str(ROOT / folder))


def create_app(state=None):
    os.environ.setdefault('CTXCOMP_DISABLE_RESPONSE_REUSE', '1')
    os.environ.setdefault('PKPD_DEMO_PROVISIONAL_RULES', '1')
    os.environ.setdefault('PKPD_DEMO_LIGHTWEIGHT_DATA', '1')
    from demo.api import create_app as factory
    state = Path(state) if state else ROOT / 'state'
    prefect_home = state / 'prefect'
    prefect_home.mkdir(parents=True, exist_ok=True)
    os.environ['PREFECT_HOME'] = str(prefect_home.resolve())
    os.environ.setdefault('PREFECT_SERVER_ANALYTICS_ENABLED', 'false')
    return factory(ROOT, state)


def configure_model(provider='codex', model=None, reasoning_effort='high', api_base=None):
    if provider not in {'codex', 'openai', 'claude'}:
        raise ValueError('Choose codex, openai or claude.')
    if provider != 'codex' and not model:
        raise ValueError('Supply --model with the exact model name exposed by this provider.')
    os.environ['CTXCOMP_MODEL_PROVIDER'] = provider
    key = {'codex': 'CTXCOMP_CODEX_MODEL', 'openai': 'CTXCOMP_OPENAI_MODEL', 'claude': 'CTXCOMP_CLAUDE_MODEL'}[provider]
    os.environ[key] = model or 'gpt-6.1-sol'
    os.environ['CTXCOMP_CODEX_REASONING_EFFORT'] = reasoning_effort
    if api_base:
        if provider != 'openai':
            raise ValueError('--api-base is used only with --provider openai.')
        from urllib.parse import urlparse
        parsed = urlparse(api_base)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Use an HTTP(S) API base URL without embedded credentials.')
        os.environ['CTXCOMP_OPENAI_BASE_URL'] = api_base.rstrip('/')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Local PK/PD demo with live execution through Data.')
    parser.add_argument('--port', type=int, default=8772)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--provider', choices=['codex', 'openai', 'claude'], default='codex')
    parser.add_argument('--model')
    parser.add_argument('--api-base', help='OpenAI-compatible base URL including /v1; credentials use environment variables.')
    parser.add_argument('--allow-response-reuse', action='store_true',
                        help='Opt into historical response caches. Disabled for fresh acceptance.')
    parser.add_argument('--reasoning-effort', choices=['low','medium','high','xhigh','max','ultra'], default='high')
    args = parser.parse_args()
    os.environ['CTXCOMP_DISABLE_RESPONSE_REUSE'] = '0' if args.allow_response_reuse else '1'
    try:
        configure_model(args.provider, args.model, args.reasoning_effort, args.api_base)
    except ValueError as exc:
        parser.error(str(exc))
    import uvicorn
    uvicorn.run(create_app(args.state), host='127.0.0.1', port=args.port)

