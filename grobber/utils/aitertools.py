import logging

__all__ = ["AIterable", "AFunction",
           "aiter", "as_completed", "anext", "alist",
           "maybe_await", "amap", "afilter",
           "get_first"]

import asyncio
import inspect
from typing import Any, AsyncIterable, AsyncIterator, Awaitable, Callable, Container, Iterable, List, Optional, \
    Sequence, Set, Tuple, Type, TypeVar, Union, cast, overload

log = logging.getLogger(__name__)

_DEFAULT = object()

T = TypeVar("T")
R = TypeVar("R")

AIterable = Union[Iterable[T], AsyncIterable[T]]
AFunction = Union[Callable[[T], R], Callable[[T], Awaitable[R]]]


def aiter(iterable: AIterable[T]) -> AsyncIterator[T]:
    """Convert any kind of iterable to an async iterable"""
    if isinstance(iterable, AsyncIterator):
        return iterable
    elif isinstance(iterable, AsyncIterable):
        return iterable.__aiter__()
    elif isinstance(iterable, Iterable):
        async def gen() -> AsyncIterator[T]:
            for item in iterable:
                yield item

        return gen()
    else:
        raise TypeError(f"Type {type(iterable)} is not aiterable.")


async def as_completed(iterable: Iterable[Awaitable[T]]) -> AsyncIterator[T]:
    if not isinstance(iterable, Sequence):
        iterable = set(iterable)

    for fut in asyncio.as_completed(iterable):
        fut = cast(asyncio.Future, fut)
        yield await fut


async def anext(iterable: AIterable[T], default: Any = _DEFAULT) -> T:
    try:
        if isinstance(iterable, AsyncIterator):
            return await iterable.__anext__()
        else:
            return next(iterable)
    except (StopAsyncIteration, StopIteration):
        if default is _DEFAULT:
            # let's make sure it's unified
            raise StopAsyncIteration
        else:
            return default


@overload
async def alist(iterable: AIterable[T], constructor: tuple) -> Tuple[T]: ...


@overload
async def alist(iterable: AIterable[T], constructor: list) -> List[T]: ...


@overload
async def alist(iterable: AIterable[T]) -> List[T]: ...


@overload
async def alist(iterable: AIterable[T], constructor: set) -> Set[T]: ...


async def alist(iterable: AIterable[T], constructor: Type[Container] = list) -> Container[T]:
    # noinspection PyArgumentList
    return constructor([item async for item in aiter(iterable)])


async def maybe_await(obj: Union[Awaitable[T], T]) -> T:
    if inspect.isawaitable(obj):
        return await obj
    else:
        return obj


async def amap(func: AFunction, iterable: AIterable[T]) -> AsyncIterator[R]:
    async for item in aiter(iterable):
        yield await maybe_await(func(item))


async def afilter(func: Optional[AFunction], iterable: AIterable[T]) -> AsyncIterator[T]:
    async for item in aiter(iterable):
        if func is None:
            if item:
                yield item
        elif await maybe_await(func(item)):
            yield item


async def get_first(coros: Iterable[Awaitable[T]],
                    predicate: Callable[[T], Union[bool, Awaitable[bool]]] = bool, *,
                    reject_exceptions: bool = True,
                    cancel_running: bool = True) -> Optional[T]:
    while coros:
        done, coros = await asyncio.wait(list(coros), return_when=asyncio.FIRST_COMPLETED)
        if done:
            try:
                result = next(iter(done)).result()
            except Exception as e:
                if reject_exceptions:
                    log.info(f"rejecting exception {e} from {coros} in {done}")
                    result = None
                    res = False
                else:
                    raise
            else:
                res = predicate(result)
                if inspect.isawaitable(res):
                    res = await res

            if not res:
                continue

            if cancel_running:
                for coro in coros:
                    coro.cancel()

            return result

    return None
