__all__ = ["AsyncFormatter",
           "create_response", "error_response",
           "add_http_scheme", "parse_js_json", "external_url_for", "format_available", "do_later",
           "anext", "alist", "get_first",
           "fuzzy_bool", "get_certainty"]

import asyncio
import json
import logging
import re
from difflib import SequenceMatcher
from string import Formatter
from typing import Any, Awaitable, Dict, List, Optional, TypeVar, Union

from quart import url_for

from .aiter import *
from .async_string_formatter import AsyncFormatter
from .response import *

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


def fuzzy_bool(s: Optional[str]) -> bool:
    if s:
        return str(s).lower() in {"true", "t", "yes", "y", "1"}
    return False


def get_certainty(a: str, b: str) -> float:
    return round(SequenceMatcher(a=a, b=b).ratio(), 2)


RE_JSON_EXPANDER = re.compile(r"(['\"])?([a-z0-9A-Z_]+)(['\"])?(\s)?:(?=(\s)?[\[\d\"'{])", re.DOTALL)
RE_JSON_REMOVE_TRAILING_COMMA = re.compile(r"([\]}])\s*,(?=\s*[\]}])")


def parse_js_json(text: str):
    valid_json = RE_JSON_EXPANDER.sub("\"\\2\": ", text).replace("'", "\"")
    valid_json = RE_JSON_REMOVE_TRAILING_COMMA.sub(r"\1", valid_json)
    return json.loads(valid_json)


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


def do_later(target: Awaitable) -> None:
    async def safe_run(aw: Awaitable) -> None:
        try:
            await aw
        except Exception:
            log.exception(f"Something went wrong while awaiting {target}")

    asyncio.ensure_future(safe_run(target))