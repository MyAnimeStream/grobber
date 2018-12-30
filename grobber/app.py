import logging
import os

import sentry_sdk
from quart import Quart, Response, request

from . import __info__, sources, telemetry
from .blueprints import *
from .exceptions import GrobberException
from .models import UID
from .telemetry import API_EXCEPTIONS, API_REQUESTS
from .utils import *

log = logging.getLogger(__name__)

app = Quart("grobber", static_url_path="/")

app.url_map.converters["UID"] = UID

app.register_blueprint(anime_blueprint)
app.register_blueprint(debug_blueprint)

host_url = os.getenv("HOST_URL")
if host_url:
    app.config["HOST_URL"] = add_http_scheme(host_url)

sentry_sdk.init(release=f"grobber@{__info__.__version__}")


@app.errorhandler(GrobberException)
def handle_grobber_exception(exc: GrobberException) -> Response:
    API_EXCEPTIONS.labels(exc.name).inc()
    return error_response(exc)


@app.teardown_appcontext
def teardown_app_context(*_):
    do_later(sources.save_dirty())


@app.before_serving
async def before_serving():
    log.info(f"grobber version {__info__.__version__} running!")


@app.before_request
async def before_request():
    log.info(request.endpoint or request.path)
    API_REQUESTS.labels(request.method, request.endpoint).inc()


@app.after_request
async def after_request(response: Response) -> Response:
    response.headers["Grobber-Version"] = __info__.__version__
    return response


@app.route("/dolos-info")
async def get_dolos_info() -> Response:
    return create_response(id="grobber", version=__info__.__version__)


@app.route("/metrics")
async def get_metrics() -> Response:
    metrics, content_type = telemetry.get_metrics()
    return Response(metrics, content_type=content_type)
