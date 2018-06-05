#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2018 Kaede Hoshikawa
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

import asyncio
import typing
import magichttp
import ssl

if typing.TYPE_CHECKING:
    from . import constants  # noqa: F401


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


class HttpConnection(magichttp.HttpClientProtocol):  # type: ignore
    def __init__(
            self, conn_id: HttpConnectionId, chunk_size: int,
            idle_timeout: int) -> None:
        super().__init__(http_version=conn_id.http_version)

        self._conn_lost_event = asyncio.Event()

        self._conn_id = conn_id
        self._chunk_size = chunk_size
        self._idle_timeout = idle_timeout

        self._idle_timer: Optional[asyncio.Handle] = None

    def _set_idle_timeout(self) -> None:
        if self._idle_timer is not None:
            self._cancel_idle_timeout()

        loop = asyncio.get_event_loop()
        self._idle_timer = loop.call_later(
            self._idle_timeout, self.transport.close)

    def _cancel_idle_timeout(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    async def _send_request(
        self, __request: "messages.PendingRequest", *,
            read_response_body: bool,
            max_body_size: int) -> "messages.Response":
        try:
            self._cancel_idle_timeout()
            if "content-length" not in __request.headers.keys():
                try:
                    body_len = await __request.body.calc_len()

                except NotImplementedError:
                    __request.headers.setdefault(
                        "transfer-encoding", "chunked")

                if body_len > 0:
                    __request.headers.setdefault(
                        "content-length", str(body_len))

            try:
                writer = await self.write_request(
                    __request.method,
                    uri=__request.uri,
                    authority=__request.authority,
                    headers=__request.headers)

                while True:
                    try:
                        body_chunk = await __request.body.read(
                            self._chunk_size)

                    except EOFError:
                        break

                    writer.write(body_chunk)
                    await writer.flush()

                writer.finish()

                reader = await writer.read_response()

                try:
                    res_body = await reader.read(max_body_size + 1)

                except magichttp.ReadFinishedError:
                    res_body = b""

                if len(res_body) > max_body_size:
                    raise exceptions.ResponseEntityTooLarge(
                        "Response body is too large.")

            except (magichttp.ReadAbortedError,
                    magichttp.WriteAbortedError,
                    magichttp.WriteAfterFinishedError) as e:
                raise exceptions.ConnectionClosed("Connection closed.") from e

            self._set_idle_timeout()

            return messages.Response(
                messages.Request(writer), reader=reader, body=res_body)

        except magichttp.EntityTooLargeError as e:
            self.transport.close()

            raise exceptions.ResponseEntityTooLarge from e

        except Exception:
            self.transport.close()

            raise

    async def _close_conn(self) -> None:
        self.transport.close()

        await self._conn_lost_event.wait()

    def _closing(self) -> bool:
        return typing.cast(bool, self.transport.is_closing())

    def connection_lost(self, exc: Optional[Exception]) -> None:
        super().connection_lost(exc)

        self._conn_lost_event.set()

    @staticmethod
    async def connect(
            __id: HttpConnectionId, timeout: int,
            tls_context: Optional[ssl.SSLContext],
            chunk_size: int, idle_timeout: int)-> "HttpConnection":
        def create_conn() -> "HttpConnection":
            return HttpConnection(
                conn_id=__id, chunk_size=chunk_size, idle_timeout=idle_timeout)

        loop = asyncio.get_event_loop()

        try:
            _, conn = await asyncio.wait_for(
                loop.create_connection(
                    create_conn, __id.hostname, __id.port,
                    ssl=tls_context, server_hostname=__id.hostname),
                timeout)

        except asyncio.TimeoutError as e:
            raise exceptions.RequestTimeout(
                "Failed to connect to remote host.") from e

        return typing.cast(HttpConnection, conn)
