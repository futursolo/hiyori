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

import asyncio
import ipaddress

from .. import exceptions
from . import base


class SystemResolver(base.BaseResolver):
    """
    This resolver implements the `getaddrinfo()` provided by the event loop.

    This is the fallback implementation when no other implementation is
    available.

    This implementation is perfectly fine to be used when the operating
    system already caches DNS requests. This is the case on Windows, macOS and
    FreeBSD with :code:`local_unbound` enabled.

    .. important::

        This implementation will always look up the hosts file as it uses
        operating system mechanism to resolve hostnames.
    """

    async def lookup_now(self, host: str, port: int) -> base.ResolvedResult:
        try:
            loop = asyncio.get_event_loop()

            avail_hosts = set()

            results = await loop.getaddrinfo(host, port)

            for result in results:
                avail_hosts.add(
                    (ipaddress.ip_address(result[-1][0]), int(result[-1][1]))
                )

            return base.ResolvedResult(
                host=host,
                port=port,
                results=avail_hosts,  # type: ignore
                ttl=self._min_ttl,
            )

        except OSError as e:
            raise exceptions.UnresolvableHost(
                f"Failed to resolve {host}:{port}"
            ) from e


__all__ = ["SystemResolver"]
