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

from typing import Optional, Set, Tuple, Union
import asyncio
import contextlib
import ipaddress
import pathlib

from .. import exceptions, http_client, resolvers
from . import base

__all__ = ["HttpsResolver"]

_RESULTS = Set[
    Union[
        Tuple[
            Union[ipaddress.IPv4Address, ipaddress.IPv6Address],
            int,
        ],
        pathlib.Path,
    ]
]


class HttpsResolver(base.BaseResolver):
    """
    This resolver implements a dns resolver that resolves via DNS over HTTPS.

    In addition to the arguments accepted by :class:`..base.BaseResolver`,
    it also accepts the following arguments:

    :arg fallback_resolver: A fallback resolver to resolve domain name in the
        :code:`dns_url`.
    :arg respect_hosts_file: Whether to look up in hosts file.
    :arg dns_url: The URL of DNS server. By default this resolver uses
        Cloudflare's DNS URL. Server MUST support :code:`application/dns-json`
        response type.
    """

    def __init__(
        self,
        *,
        min_ttl: int = 60,
        respect_remote_ttl: bool = True,
        respect_hosts_file: bool = True,
        fallback_resolver: Optional[base.BaseResolver] = None,
        dns_url: str = "https://cloudflare-dns.com/dns-query",
    ) -> None:
        super().__init__(
            min_ttl=min_ttl, respect_remote_ttl=respect_remote_ttl
        )

        if respect_hosts_file:
            self._hosts_resolver: Optional[
                resolvers.HostsResolver
            ] = resolvers.HostsResolver(
                min_ttl=min_ttl, respect_remote_ttl=respect_remote_ttl
            )

        else:
            self._hosts_resolver = None

        self._dns_url = dns_url

        # Prevent dead loop
        if (
            fallback_resolver is None
            and resolvers.DefaultResolver is self.__class__
        ):
            fallback_resolver = resolvers.SystemResolver()

        self._resolver = http_client.HttpClient(
            timeout=15, resolver=fallback_resolver
        )

    async def query(
        self, host: str, port: int, record_type: str
    ) -> Tuple[_RESULTS, int]:
        assert record_type in (
            "A",
            "AAAA",
        ), "Currently only supports A or AAAA record."

        try:
            resp = await self._resolver.get(
                self._dns_url,
                path_args={"name": host, "type": record_type},
                headers={"accept": "application/dns-json"},
            )

            msg = resp.body.to_json()

            results: _RESULTS = set()

            ttl: Optional[int] = None

            if not isinstance(msg, dict):
                raise ValueError("Response is not a dictionary.")

            for record in msg["Answer"]:
                results.add((ipaddress.ip_address(record["data"]), port))
                if ttl is None or ttl > record["TTL"]:
                    ttl = record["TTL"]

            if not isinstance(ttl, int):
                raise ValueError("TTL is not valid.")

            return (results, ttl)

        except (
            exceptions.BaseHiyoriException,
            TimeoutError,
            KeyError,
            ValueError,
            IndexError,
            TypeError,
        ) as e:
            raise exceptions.UnresolvableHost(
                f"Failed to resolve {host}:{port}."
            ) from e

    async def lookup_now(self, host: str, port: int) -> base.ResolvedResult:
        if self._hosts_resolver is not None:
            with contextlib.suppress(exceptions.UnresolvableHost):
                return await self._hosts_resolver.lookup(host, port)

        results: Set[
            Union[
                Tuple[
                    Union[ipaddress.IPv4Address, ipaddress.IPv6Address],
                    int,
                ],
                pathlib.Path,
            ]
        ] = set()

        ttl: Optional[int] = None

        done, _ = await asyncio.wait(
            [
                asyncio.ensure_future(self.query(host, port, "A")),
                asyncio.ensure_future(self.query(host, port, "AAAA")),
            ]
        )

        for tsk in done:
            with contextlib.suppress(exceptions.UnresolvableHost):
                _results, _ttl = tsk.result()
                results.update(_results)

                if ttl is None or ttl > _ttl:
                    ttl = _ttl

        if ttl is None or ttl < self._min_ttl:
            ttl = self._min_ttl

        if not results:
            try:
                for tsk in done:
                    tsk.result()

                raise ValueError(
                    "DNS Server didn't return any results for {host}:{port}."
                )

            except RuntimeError as e:
                raise exceptions.UnresolvableHost(
                    f"Failed to resolve {host}:{port}."
                ) from e

        return base.ResolvedResult(
            host=host, port=port, results=results, ttl=ttl
        )
