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

from typing import Dict, Union, List

import time
import ipaddress
import os
import pathlib
import platform

from . import base
from .. import exceptions


if platform.system() == "Windows":
    _SYSTEM_DEFAULT_HOST_PATH = (
        pathlib.Path(os.environ["SystemRoot"])
        / "system32"
        / "drivers"
        / "etc"
        / "hosts"
    )

else:
    _SYSTEM_DEFAULT_HOST_PATH = pathlib.Path("/etc/hosts")


class HostsResolver(base.BaseResolver):
    """
    This resolver resolves names by reading hosts file.
    """

    def __init__(
        self,
        *,
        min_ttl: int = 60,
        respect_remote_ttl: bool = True,
        host_path: Union[str, os.PathLike[str]] = _SYSTEM_DEFAULT_HOST_PATH,
    ) -> None:
        super().__init__(
            min_ttl=min_ttl, respect_remote_ttl=respect_remote_ttl
        )

        self._hosts_content: Dict[
            str, List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]
        ] = {}
        self._last_read = -self._min_ttl

        self.host_path = pathlib.Path(host_path)

    async def _read_hosts(self) -> None:
        if self._last_read + self._min_ttl > time.monotonic():
            return

        self._hosts_content = {}

        with self.host_path.open() as f:
            for line in f.readlines():
                # Remove comments
                line = line.rstrip().split("#", 1)[0]

                if not line:
                    continue

                try:
                    ip_s, host = [i.strip() for i in line.split() if i.strip()]

                    ip = ipaddress.ip_address(ip_s)

                # Ignore invalid lines.
                except (ValueError, IndexError):
                    continue

                self._hosts_content.setdefault(host, [])
                self._hosts_content[host].append(ip)

        self._last_read = int(time.monotonic())

    async def lookup_now(self, host: str, port: int) -> base.ResolvedResult:
        try:
            await self._read_hosts()

            ips = self._hosts_content[host]

            results = [(ip, port) for ip in ips]

            return base.ResolvedResult(
                host=host,
                port=port,
                results=set(results),  # type: ignore
                ttl=self._min_ttl,
            )

        except (KeyError, OSError) as e:
            raise exceptions.UnresolvableHost(
                f"Failed to resolve {host}:{port}"
            ) from e
