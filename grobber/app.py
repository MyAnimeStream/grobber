# noinspection PyUnresolvedReferences
import logging
import os
from typing import cast

import sentry_sdk
from quart import Quart, Request, Response, request

from . import __info__, anime, locals
from .blueprints import *
from .exceptions import GrobberException
from .uid import UID
from .utils import *

request = cast(Request, request)

log = logging.getLogger(__name__)

app = Quart("grobber", static_url_path="/")

app.url_map.converters["UID"] = UID

app.register_blueprint(anime_blueprint)

host_url = os.getenv("HOST_URL")
if host_url:
    app.config["HOST_URL"] = add_http_scheme(host_url)

sentry_sdk.init(release=f"grobber@{__info__.__version__}")


@app.errorhandler(GrobberException)
def handle_grobber_exception(exc: GrobberException) -> Response:
    return error_response(exc)


@app.errorhandler(500)
def handle_internal_exception(_: Exception) -> Response:
    log.exception("internal error")
    return error_response(GrobberException("Internal Error"), status_code=500)


@app.teardown_appcontext
def teardown_app_context(*_):
    anime.teardown()


@app.before_serving
async def before_serving():
    log.info(f"grobber version {__info__.__version__} running!")
    await locals.before_serving()


@app.before_request
async def before_request():
    endpoint = request.endpoint

    args = " ".join(f"{key}={value}" for key, value in request.args.items())
    log.info(f"{request.method} {endpoint or request.path} {args}")


@app.route("/dolos-info")
@app.route("/grobber-info")
async def get_dolos_info() -> Response:
    return create_response(id="grobber", version=__info__.__version__)
