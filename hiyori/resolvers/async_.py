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

from typing import Optional, List

from . import base

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
        domain.
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

            self._respect_hosts_file = respect_hosts_file

            self._dns_servers = dns_servers

            self._resolver = aiodns.DNSResolver(self._dns_servers)

        async def lookup_now(
            self, host: str, port: int
        ) -> base.ResolvedResult:
            raise NotImplementedError

    __all__.append("AsyncResolver")

except ImportError:
    pass
