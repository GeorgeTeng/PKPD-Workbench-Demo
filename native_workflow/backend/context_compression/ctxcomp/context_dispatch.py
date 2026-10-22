"""Task-local session and prepared input; other threads use the mandatory gateway."""
from contextlib import contextmanager
from contextvars import ContextVar

_handler = ContextVar('contextbuilder_handler', default=None)
_wire = ContextVar('contextbuilder_model_wire', default=None)


@contextmanager
def sending(request, wire, schema=None):
    from .io import digest
    token = _wire.set((digest(request),wire,schema or request['payload']['schema']))
    try:
        yield
    finally:
        _wire.reset(token)


def prepared(request):
    from .io import digest
    entry=_wire.get()
    return entry is not None and entry[0]==digest(request)


def transport_schema(request):
    if not prepared(request):raise ValueError('No prepared transport schema')
    return _wire.get()[2]


def current():
    return _handler.get()


def model_input(request):
    if prepared(request):
        return _wire.get()[1]
    from research_pipeline.context_routes import managed
    if managed(request):
        raise ValueError('Compression/Data transport requires a prepared ContextBuilder input')
    owner = getattr(current(), '__self__', None)
    projector = getattr(owner, 'model_input', None)
    if projector is not None:
        return projector(request)
    from .model_view import view
    return view(request)


@contextmanager
def install(handler):
    if current() is not None:
        raise RuntimeError('A context dispatch session is already active')
    token = _handler.set(handler)
    try:
        yield
    finally:
        _handler.reset(token)
