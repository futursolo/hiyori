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

from typing import List, Optional, Set, Tuple, Union
import asyncio
import contextlib
import ipaddress
import pathlib

from .. import exceptions
from . import base, hosts

__all__ = []

try:
    import aiodns

    class AsyncResolver(base.BaseResolver):
        """
        This resolver implements a dns resolver using :code:`aiodns`.

        This is the default implementation if aiodns is installed.

        In addition to the arguments accepted by :class:`..base.BaseResolver`,
        it also accepts the following arguments:

        :arg respect_hosts_file: Whether to look up in hosts file.
        :arg dns_servers: List of DNS servers to use. :code:`None` if system
        DNS servers should be used.
        """

        def __init__(
            self,
            *,
            min_ttl: int = 60,
            respect_remote_ttl: bool = True,
            respect_hosts_file: bool = True,
            dns_servers: Optional[List[str]] = None,
        ) -> None:
            super().__init__(
                min_ttl=min_ttl, respect_remote_ttl=respect_remote_ttl
            )

            if respect_hosts_file:
                self._hosts_resolver: Optional[
                    hosts.HostsResolver
                ] = hosts.HostsResolver(
                    min_ttl=min_ttl, respect_remote_ttl=respect_remote_ttl
                )

            else:
                self._hosts_resolver = None

            self._dns_servers = dns_servers

            self._resolver = aiodns.DNSResolver(self._dns_servers)

        async def lookup_now(
            self, host: str, port: int
        ) -> base.ResolvedResult:
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
                    self._resolver.query(host, "A"),
                    self._resolver.query(host, "AAAA"),
                ]
            )

            for tsk in done:
                with contextlib.suppress(aiodns.error.DNSError):
                    for result in tsk.result():
                        with contextlib.suppress(ValueError):
                            ip = ipaddress.ip_address(result.host)

                            results.add((ip, port))

                            if ttl is None or ttl > result.ttl:
                                ttl = result.ttl

            if ttl is None or ttl < self._min_ttl:
                ttl = self._min_ttl

            if not results:
                try:
                    for tsk in done:
                        tsk.result()

                    raise RuntimeError(
                        "This shouldn't happen. Please file an issue."
                    )

                except (RuntimeError, aiodns.error.DNSError) as e:
                    raise exceptions.UnresolvableHost(
                        f"Failed to resolve {host}:{port}."
                    ) from e

            return base.ResolvedResult(
                host=host, port=port, results=results, ttl=ttl
            )

    __all__.append("AsyncResolver")

except ImportError:
    pass
