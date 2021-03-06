import ast
import asyncio
import json
import logging
import re
from string import Formatter
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Match, Optional, Tuple, TypeVar, Union

from quart import url_for

from . import aitertools, mongo, mutate, text
from .aitertools import *
from .async_string_formatter import AsyncFormatter
from .mongo import *
from .mutate import *
from .response import *
from .text import *

__all__ = ["AsyncFormatter",
           "create_response", "error_response",
           "add_http_scheme", "parse_js_json", "external_url_for", "format_available", "do_later",
           "fuzzy_bool",
           *aitertools.__all__,
           *mongo.__all__,
           *mutate.__all__,
           *text.__all__]

log = logging.getLogger(__name__)

T2 = TypeVar("T2")
_DEFAULT = object()


def add_http_scheme(link: str, base_url: str = None, *, _scheme="http") -> str:
    if link.startswith("//"):
        return f"{_scheme}:{link}"
    elif not link.startswith(("http://", "https://")):
        if base_url:
            return base_url.rstrip("/") + "/" + link
        return f"{_scheme}://{link}"
    return link


def fuzzy_bool(s: Optional[str], *, default: bool = False) -> bool:
    if s is None:
        return default

    if s:
        return str(s).lower() in {"true", "t", "yes", "y", "1"}

    return False


def perform_safe(func: Callable, *args, **kwargs) -> Tuple[Optional[Any], Optional[Exception]]:
    try:
        res = func(*args, **kwargs)
    except Exception as e:
        return None, e
    else:
        return res, None


RE_JSON_EXPANDER = re.compile(r"([`'])?([a-z0-9A-Z_]+)([`'])?\s*:(?=\s*[\[\d`'\"{])", re.DOTALL)
RE_JSON_REMOVE_TRAILING_COMMA = re.compile(r"([\]}\"])\s*,(?=\s*[\]}])")

RE_JSON_VARIABLE_DETECT = re.compile(r"\"(?P<key>[^\"]+?)\"\s*:\s*(?P<value>[^`'\"][a-zA-Z]+)\b,?")


def parse_js_json(text: str, *, variables: Mapping[str, Any] = None) -> Any:
    def _try_load(_text) -> Tuple[Optional[Exception], Any]:
        _exc = _data = None

        _data, _exc = perform_safe(json.loads, _text)
        if _exc is None:
            return None, _data

        _data, _e = perform_safe(ast.literal_eval, _text)
        if _e is None:
            return None, _data

        _e.__cause__ = _exc
        return _e, None

    valid_json = RE_JSON_EXPANDER.sub("\"\\2\": ", text).replace("'", "\"")
    valid_json = RE_JSON_REMOVE_TRAILING_COMMA.sub(r"\1", valid_json)

    e, data = _try_load(valid_json)
    if e is None:
        return data

    log.debug(f"failed to load js json data: {e!r}")

    _valid_names = {"true", "false", "null", "NaN", "Infinity", "-Infinity"}

    def _replacer(_match: Match) -> str:
        _key = _match["key"]
        _variable = _match["value"]

        if _variable in _valid_names:
            _value = _variable
        elif variables:
            _value = json.dumps(variables.get(_variable))
        else:
            log.debug(f"value {_variable!r} invalid, no variables passed, replacing with null!")
            _value = "null"

        return f"\"{_key}\": {_value}"

    log.debug("trying again with invalid values removed.")
    valid_json = RE_JSON_VARIABLE_DETECT.sub(_replacer, valid_json)

    e, data = _try_load(valid_json)
    if e is None:
        return data

    log.info(f"couldn't decode js json:\nRaw:\n{text!r}\n\nParsed:\n{valid_json!r}")
    raise e


def external_url_for(endpoint: str, **kwargs):
    kwargs["_external"] = True
    kwargs["_scheme"] = "https"
    return url_for(endpoint, **kwargs)


class _ModestFormatter(Formatter):
    def get_value(self, key: Union[str, int], args: List[Any], kwargs: Dict[Any, Any]) -> Any:
        try:
            return super().get_value(key, args, kwargs)
        except (IndexError, KeyError):
            return f"{{{key}}}"


ModestFormatter = _ModestFormatter()


def format_available(text: str, *args, **kwargs) -> str:
    return ModestFormatter.format(text, *args, **kwargs)


def do_later(target: Awaitable, log_level: int = logging.WARN) -> None:
    async def safe_run(aw: Awaitable) -> None:
        try:
            await aw
        except Exception:
            log.log(log_level, f"Something went wrong while awaiting {target}")

    asyncio.ensure_future(safe_run(target))
