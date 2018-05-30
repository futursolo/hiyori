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

import asyncio
import typing
import magichttp

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

    @staticmethod
    def from_pending_request(
            __request: messages.PendingRequest) -> "HttpConnectionId":
        return HttpConnectionId(
            http_version=constants.HttpVersion.V1_1,
            authority=__request.authority,
            scheme=__request.scheme)


class HttpConnection(magichttp.HttpClientProtocol):  # type: ignore
    def __init__(self, conn_id: HttpConnectionId, chunk_size: int) -> None:
        super().__init__(http_version=conn_id.http_version)

        self._conn_lost_event = asyncio.Event()

        self._conn_id = conn_id
        self._chunk_size = chunk_size

    async def _send_request(
        self, __request: messages.PendingRequest, *,
            read_response_body: bool) -> messages.Response:
        if "content-length" not in __request.headers.keys():
            try:
                body_len = await __request.body.calc_len()

            except NotImplementedError:
                __request.headers.setdefault("transfer-encoding", "chunked")

            if body_len > 0:
                __request.headers.setdefault("content-length", str(body_len))

        writer = await self.write_request(
            __request.method,
            uri=__request.uri,
            authority=__request.authority,
            headers=__request.headers)

        while True:
            try:
                body_chunk = await __request.body.read(self._chunk_size)

            except EOFError:
                break

            writer.write(body_chunk)
            await writer.flush()

        writer.finish()
        reader = await writer.read_response()

        res_body = await reader.read()
        return messages.Response(
            messages.Request(writer), reader=reader, body=res_body)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        super().connection_lost(exc)

        self._conn_lost_event.set()
