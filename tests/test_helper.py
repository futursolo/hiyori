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

from typing import List, Optional, Type, Union
import asyncio

import magichttp

import hiyori


class _SkeletonServer(asyncio.Protocol):
    _mock_srv: Optional[asyncio.Protocol]

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        print("Connection made.")

        if helper.mock_srv_cls is None:
            transport.close()

            return

        assert helper.mock_srv_cls is not None
        self._mock_srv = helper.mock_srv_cls()

        self._mock_srv.connection_made(transport)

    def data_received(self, data: bytes) -> None:
        print(f"Data received: {data!r}.")
        helper.mock_srv = self._mock_srv

        assert self._mock_srv is not None
        self._mock_srv.data_received(data)

    def eof_received(self) -> Optional[bool]:
        print("Eof received.")

        return self._mock_srv.eof_received() if self._mock_srv else None

    def connection_lost(self, exc: Optional[Exception]) -> None:
        print("Connection lost.")
        if exc:
            print(exc)

        assert self._mock_srv is not None
        self._mock_srv.connection_lost(exc)


class MockServer(asyncio.Protocol):
    def __init__(self) -> None:
        self.transport: Optional[asyncio.BaseTransport] = None
        self.data_chunks: List[bytes] = []
        self.eof = False
        self.exc: Optional[Exception] = None
        self.conn_lost = False

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport

    def data_received(self, data: bytes) -> None:
        self.data_chunks.append(data)

    def eof_received(self) -> Optional[bool]:
        self.eof = True
        return True

    def connection_lost(self, exc: Optional[Exception]) -> None:
        self.exc = exc
        self.conn_lost = True


class TestHelper:
    """
    A test helper that controls the servers.
    """

    def __init__(self) -> None:
        self._srv = None


class _TestHelper:
    """
    Legacy Test Helper
    """

    def __init__(self) -> None:
        self.mock_srv: Optional[asyncio.Protocol] = None
        self.mock_srv_cls: Optional[Type[asyncio.Protocol]] = None

        self._srv = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        loop = asyncio.get_event_loop()
        loop.set_debug(True)
        return loop

    def run_async_test(self, *args, with_srv_cls=None):
        def decorator(coro_fn):
            async def test_coro(_self, *args, **kwargs):
                self.mock_srv_cls = with_srv_cls

                exc = None
                self._srv = await self.loop.create_server(
                    _SkeletonServer, host="localhost", port=8000
                )

                try:

                    try:
                        await asyncio.wait_for(
                            coro_fn(_self, *args, **kwargs), timeout=5
                        )

                    except Exception as e:
                        exc = e

                    if self.mock_srv:
                        self.mock_srv.transport.close()
                        self.mock_srv = None

                finally:
                    self._srv.close()
                    await self._srv.wait_closed()

                if exc:
                    raise exc

            def wrapper(_self, *args, **kwargs):
                self.loop.run_until_complete(test_coro(_self, *args, **kwargs))

            return wrapper

        if args:
            if len(args) > 1:
                raise RuntimeError("Only one positional argument is allowed.")

            if with_srv_cls is not None:
                raise RuntimeError("This is not okay.")

            return decorator(args[0])

        if with_srv_cls is None:
            raise RuntimeError("You must provide a server class.")

        return decorator

    def get_version_str(self) -> str:
        return f"hiyori/{hiyori.__version__} magichttp/{magichttp.__version__}"

    def get_version_bytes(self) -> bytes:
        return self.get_version_str().encode()

    def assert_initial_bytes(
        self, buf: Union[bytes, bytearray], first_line: bytes, *header_lines
    ) -> None:
        buf_initial = buf.split(b"\r\n\r\n")[0]
        buf_parts = buf_initial.split(b"\r\n")

        assert buf_parts.pop(0) == first_line

        assert len(buf_parts) == len(set(buf_parts))
        assert len(buf_parts) == len(header_lines)

        for line in header_lines:
            line = line % {  # noqa: S001
                b"self_ver_bytes": self.get_version_bytes()
            }
            assert line in buf_parts


helper = _TestHelper()
