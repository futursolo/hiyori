#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2020 Kaede Hoshikawa
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

from typing import NamedTuple, Optional

from . import messages
from . import exceptions
from . import constants
from . import resolvers

import asyncio
import magichttp
import ssl


class HttpConnectionId(NamedTuple):
    authority: str
    scheme: "constants.HttpScheme"
    http_version: "constants.HttpVersion"

    @property
    def port(self) -> int:
        maybe_port_str = self.authority.split(":", 1)
        if len(maybe_port_str) > 1:
            return int(maybe_port_str[1])

        elif self.scheme == constants.HttpScheme.HTTPS:
            return 443

        else:
            return 80

    @property
    def hostname(self) -> str:
        return self.authority.split(":", 1)[0]


class HttpConnection:
    """
    Internal object that controls an http connection.
    """

    def __init__(
        self,
        __conn_id: HttpConnectionId,
        *,
        max_initial_size: int,
        chunk_size: int,
        tls_context: Optional[ssl.SSLContext],
        idle_timeout: int,
        resolver: resolvers.BaseResolver,
    ) -> None:
        self.conn_id = __conn_id

        self._max_initial_size = max_initial_size
        self._chunk_size = chunk_size
        self._tls_context = tls_context
        self._idle_timeout = idle_timeout

        self._idle_timer: Optional[asyncio.Handle] = None
        self._set_idle_timeout()

        self._resolver = resolver

        self._protocol: Optional[magichttp.HttpClientProtocol] = None
        self._closing = asyncio.Event()

    def _set_idle_timeout(self) -> None:
        self._cancel_idle_timeout()

        loop = asyncio.get_event_loop()
        self._idle_timer = loop.call_later(self._idle_timeout, self.close)

    def _cancel_idle_timeout(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    async def get_ready(self) -> None:
        self._cancel_idle_timeout()

        if self.closing():
            raise RuntimeError("This connection is closing.")

        if (
            self._protocol is not None
            and not self._protocol.transport.is_closing()
        ):
            return

        def create_conn() -> magichttp.HttpClientProtocol:
            class _Protocol(magichttp.HttpClientProtocol):
                MAX_INITIAL_SIZE = self._max_initial_size

            return _Protocol(http_version=self.conn_id.http_version)

        result = await self._resolver.lookup(
            self.conn_id.hostname, self.conn_id.port
        )

        _, self._protocol = await result.connect_fastest(
            create_conn, self._tls_context
        )

    async def send_request(
        self,
        __request: "messages.PendingRequest",
        *,
        read_response_body: bool,
        max_body_size: int,
    ) -> "messages.Response":
        await self.get_ready()
        assert self._protocol is not None

        if "content-length" not in __request.headers.keys():
            try:
                body_len = await __request.body.calc_len()

            except NotImplementedError:
                __request.headers.setdefault("transfer-encoding", "chunked")

            if body_len > 0:
                __request.headers.setdefault("content-length", str(body_len))

        try:
            writer = await self._protocol.write_request(
                __request.method,
                uri=__request.uri,
                authority=__request.authority,
                headers=__request.headers,
            )

            while True:
                try:
                    body_chunk = await __request.body.read(self._chunk_size)

                except EOFError:
                    break

                writer.write(body_chunk)
                await writer.flush()

            writer.finish()
            reader = await writer.read_response()

            if read_response_body:
                body_buf = bytearray()

                try:
                    while True:
                        body_buf += await reader.read(
                            max_body_size + 1 - len(body_buf)
                        )

                        if len(body_buf) > max_body_size:
                            reader.abort()

                            raise exceptions.ResponseEntityTooLarge(
                                "Response body is too large."
                            )

                except magichttp.ReadFinishedError:
                    res_body = bytes(body_buf)

            else:
                res_body = b""
                self.close()

        except (
            magichttp.ReadAbortedError,
            magichttp.WriteAbortedError,
            magichttp.WriteAfterFinishedError,
        ) as e:
            raise exceptions.ConnectionClosed("Connection closed.") from e

        except magichttp.ReceivedDataMalformedError as e:
            raise exceptions.BadResponse from e

        except magichttp.EntityTooLargeError as e:
            raise exceptions.ResponseEntityTooLarge from e

        self._set_idle_timeout()

        return messages.Response(
            messages.Request(writer), reader=reader, body=res_body, conn=self
        )

    def close(self) -> None:
        self._closing.set()

        if self._protocol is not None:
            self._protocol.close()

    async def wait_closed(self) -> None:
        await self._closing.wait()

        if self._protocol is not None:
            await self._protocol.wait_closed()

    def closing(self) -> bool:
        return self._closing.is_set()
