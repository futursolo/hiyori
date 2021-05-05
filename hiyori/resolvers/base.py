#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2021 Kaede Hoshikawa
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from typing import Callable, Dict, Optional, Set, Tuple, TypeVar, Union
import abc
import asyncio
import ipaddress
import pathlib
import ssl
import time

from .. import exceptions

_RECORD = Union[
    Tuple[ipaddress.IPv4Address, int],
    Tuple[ipaddress.IPv6Address, int],
    pathlib.Path,
]

_Proto = TypeVar("_Proto", bound=asyncio.Protocol)


async def open_connection(
    record: _RECORD,
    *,
    host: str,
    factory: Callable[[], _Proto],
    tls_ctx: Optional[ssl.SSLContext] = None,
) -> Tuple[asyncio.BaseTransport, _Proto]:
    loop = asyncio.get_event_loop()

    if isinstance(record, pathlib.Path):
        return await loop.create_unix_connection(  # type: ignore
            factory,
            str(record),
            ssl=tls_ctx,
            server_hostname=host if tls_ctx else None,
        )

    ip, port = record
    ip_str = str(ip)

    return await loop.create_connection(  # type: ignore
        factory,
        host=ip_str,
        port=port,
        ssl=tls_ctx,
        server_hostname=host if tls_ctx else None,
    )


class ResolvedResult:
    """
    A resolved DNS Result.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        results: Set[_RECORD],
        ttl: int,
    ) -> None:
        self.host = host
        self.port = port
        self.results = results
        self.ttl = ttl
        self.resolved_at = time.monotonic()

        self._fastest: Optional[_RECORD] = None

    def expired(self) -> bool:
        if self.ttl < 0:
            return False

        return time.monotonic() - self.ttl > self.resolved_at

    async def connect_fastest(
        self, factory: Callable[[], _Proto], tls_ctx: Optional[ssl.SSLContext]
    ) -> Tuple[asyncio.BaseTransport, _Proto]:
        """
        Try to connect to fastest available address.
        """

        # Connect to cached fastest host.
        if self._fastest:
            try:
                return await open_connection(
                    self._fastest,
                    host=self.host,
                    factory=factory,
                    tls_ctx=tls_ctx,
                )

            except asyncio.CancelledError:
                raise

            except Exception:
                # Failed to connect to fastest host, will try the rest.
                self._fastest = None

        # Create a task for each result.
        coros = {
            record: asyncio.ensure_future(
                open_connection(
                    record,
                    host=self.host,
                    factory=factory,
                    tls_ctx=tls_ctx,
                )
            )
            for record in self.results
        }

        def read_result() -> Optional[
            Tuple[_RECORD, Tuple[asyncio.BaseTransport, _Proto]]
        ]:
            """Try to read first successful result."""

            for k, v in coros.items():
                try:
                    return (k, v.result())

                except Exception:
                    continue

            return None

        pending = set(coros.values())

        try:
            while len(pending) > 0:
                _, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Return result if available.
                result = read_result()
                if result:
                    (record, (transport, protocol)) = result
                    self._fastest = record

                    return (transport, protocol)

        finally:
            # Cancel all remaining coroutines.
            if coros:
                for coro in coros.values():
                    coro.cancel()

                await asyncio.wait(
                    set(coros.values()), return_when=asyncio.ALL_COMPLETED
                )

        raise exceptions.UnresolvableHost(
            f"{self.host}:{self.port} is not reachable."
        )


_CACHE_KEY = Tuple[str, int]


class BaseResolver(abc.ABC):
    """
    The Base Class for Resolvers.

    This class defines methods that all resolvers should implement.

    :arg min_ttl: The minimum seconds to wait for records before requerying.
    :arg respect_remote_ttl: Whether to respect the ttl provided by the
        backend if one is available and higher than :code:`min_ttl`.
    """

    def __init__(
        self,
        *,
        min_ttl: int = 60,
        respect_remote_ttl: bool = True,
    ) -> None:
        self._min_ttl = min_ttl
        self._respect_remote_ttl = respect_remote_ttl

        self._cache: Dict[_CACHE_KEY, ResolvedResult] = {}

        self._overrides: Dict[_CACHE_KEY, ResolvedResult] = {}

    def override(self, host: str, port: int, resolve_to: _RECORD) -> None:
        """
        Override the provided hostname - port combination
        to a specific address.
        """
        self._overrides[(host, port)] = ResolvedResult(
            host=host, port=port, results=set([resolve_to]), ttl=-1
        )

    def remove_override(self, host: str, port: int) -> None:
        del self._overrides[(host, port)]

    async def lookup(self, host: str, port: int) -> ResolvedResult:
        """
        Try to resolve the provided hostname - port combination.

        This returns immediately if host is already an ip address.

        All results are cached for the period that is specified by the

        :code:`minimum_ttl` argument provided when creating the resolver.
        """
        cache_key = (host, port)

        overriden_result = self._overrides.get(cache_key)

        if overriden_result:
            return overriden_result

        cached_result = self._cache.get(cache_key)

        if cached_result is not None:
            if cached_result.expired():
                del self._cache[cache_key]

            else:
                return cached_result

        fresh_result = await self.lookup_now(host, port)

        self._cache[cache_key] = fresh_result

        return fresh_result

    @abc.abstractmethod
    async def lookup_now(self, host: str, port: int) -> ResolvedResult:
        """
        Look up the record without caching.

        This should send the request immediately to the underlying
        implementation. If the underlying implementation has caching mechanism
        that can be disabled / bypassed. Then it should be disabled / bypassed.

        All resolvers MUST implement this method.
        """
        raise NotImplementedError
