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

from typing import MutableMapping, Optional, NamedTuple, Mapping, Union
from typing import Awaitable  # noqa: F401

from . import messages
from . import exceptions
from . import constants

import ssl
import collections
import magichttp
import asyncio
import weakref
import urllib.parse
import magicdict
import typing

if typing.TYPE_CHECKING:
    from . import bodies  # noqa: F401

__all__ = [
    "HttpClient",

    "get",
    "post",
    "put",
    "delete",
    "head",
    "options",
    "connect",
    "trace",
    "patch"]


class _HttpClientProtocolIdentifier(NamedTuple):
    authority: str
    scheme: constants.HttpScheme
    http_version: constants.HttpVersion

    @property
    def port(self) -> int:
        if self.authority.find(":") != -1:
            port_str = self.authority.split(":", 1)[1]
            return int(port_str)

        if self.scheme == constants.HttpScheme.HTTPS:
            return 443

        return 80

    @staticmethod
    def from_pending_request(
        __pending_request: messages.PendingRequest) -> \
            "_HttpClientProtocolIdentifier":
        return _HttpClientProtocolIdentifier(
            http_version=constants.HttpVersion.V1_1,
            authority=__pending_request.authority,
            scheme=__pending_request.scheme)


class _HttpClientProtocol(magichttp.HttpClientProtocol):  # type: ignore
    def __init__(
        self, conn_id: _HttpClientProtocolIdentifier, chunk_size: int
            ) -> None:
        super().__init__(http_version=conn_id.http_version)

        self._conn_lost_event = asyncio.Event()

        self._conn_id = conn_id
        self._chunk_size = chunk_size

    async def _send_request(
        self, __pending_request: messages.PendingRequest, *,
            read_response_body: bool) -> messages.Response:
        try:
            body_len = await __pending_request.body.calc_len()

            if body_len > 0:
                __pending_request.headers.setdefault(
                    "content-length", str(body_len))

        except NotImplementedError:
            __pending_request.headers.setdefault(
                    "transfer-encoding", "chunked")

        writer = await self.write_request(
            __pending_request.method,
            uri=__pending_request.uri, authority=__pending_request.authority,
            headers=__pending_request.headers)

        while True:
            try:
                body_chunk = await __pending_request.body.read(
                    self._chunk_size)

            except EOFError:
                break

            writer.write(body_chunk)

        writer.finish()
        reader = await writer.read_response()

        res_body = await reader.read()
        return messages.Response(
            messages.Request(writer), reader=reader, body=res_body)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        super().connection_lost(exc)

        self._conn_lost_event.set()


class HttpClient:
    def __init__(
        self, *, idle_timeout: int=10,
        timeout: int=60,
        max_initial_size: int=64 * 1024,  # 64K
        max_body_size: int=2 * 1024 * 1024,  # 2M
        allow_keep_alive: bool=True,
        chunk_size: int=128 * 1024,  # 128K
        tls_context: Optional[ssl.SSLContext]=None,
        max_idle_connections: int=100,
            max_redirects: int=10) -> None:
        self._allow_keep_alive = allow_keep_alive
        self._max_initial_size = max_initial_size

        self._max_body_size = max_body_size
        self._chunk_size = chunk_size

        self._tls_context = tls_context or \
            ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

        self._timeout = timeout
        self._idle_timeout = idle_timeout
        self._max_idle_connections = max_idle_connections

        self._max_redirects = max_redirects

        self._conns: MutableMapping[
            _HttpClientProtocolIdentifier, _HttpClientProtocol] = \
            collections.OrderedDict()

        self._pending_tsks: "weakref.WeakSet[Awaitable[bool]]" = \
            weakref.WeakSet()

    async def _get_conn(
        self, __id: _HttpClientProtocolIdentifier, prefer_cached: bool=True,
            timeout: Optional[int]=None)-> _HttpClientProtocol:
        if prefer_cached:
            if __id in self._conns.keys():
                conn = self._conns.pop(__id)

                if not conn.transport.is_closing():
                    return conn

        loop = asyncio.get_event_loop()

        try:
            _, conn = await asyncio.wait_for(  # type: ignore
                loop.create_connection(
                    lambda: _HttpClientProtocol(
                        conn_id=__id, chunk_size=self._chunk_size),
                    __id.authority, __id.port, ssl=self._tls_context \
                    if __id.scheme == constants.HttpScheme.HTTPS else None),
                self._timeout if timeout is None else timeout)

        except asyncio.TimeoutError as e:
            raise exceptions.RequestTimeout(
                "Failed to connect to remote host.") from e

        tsk = loop.create_task(conn._conn_lost_event.wait())
        self._pending_tsks.add(tsk)

        return conn

    async def _put_conn(self, __conn: _HttpClientProtocol) -> None:
        if __conn.transport.is_closing():
            return

        if self._allow_keep_alive is False:
            __conn.transport.close()

        if __conn._conn_id in self._conns.keys():
            old_conn = self._conns.pop(__conn._conn_id)
            old_conn.transport.close()

        self._conns[__conn._conn_id] = __conn

    async def send_request(
        self, __pending_request: messages.PendingRequest, *,
        read_response_body: bool=True,
            timeout: Optional[int]=None) -> messages.Response:
        identifier = _HttpClientProtocolIdentifier.from_pending_request(
            __pending_request)

        for i in range(0, 2):
            conn = await self._get_conn(
                identifier, prefer_cached=True if i == 0 else False,
                timeout=timeout)

            try:
                response = await asyncio.wait_for(conn._send_request(
                    __pending_request, read_response_body=read_response_body),
                    self._timeout if timeout is None else timeout)

                if read_response_body:
                    await self._put_conn(conn)

                return response

            except asyncio.TimeoutError as e:
                conn.transport.close()

                raise exceptions.RequestTimeout from e

            except exceptions.ConnectionClosed:
                if i == 0:
                    continue

                raise

        else:
            raise NotImplementedError

    async def fetch(
        self, __method: constants.HttpRequestMethod, __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
            ) -> messages.Response:

        parsed_url = urllib.parse.urlsplit(__url, scheme="http")

        final_path_args = magicdict.TolerantMagicDict(path_args or {})

        if parsed_url.query:
            final_path_args.update(urllib.parse.parse_qsl(parsed_url.query))

        pending_request = messages.PendingRequest(
            __method, authority=parsed_url.netloc, path=parsed_url.path or "/",
            path_args=final_path_args, scheme=parsed_url.scheme,
            headers=headers, version=constants.HttpVersion.V1_1, body=body)

        return await self.send_request(pending_request,
                                       read_response_body=read_response_body,
                                       timeout=timeout)

    async def head(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.HEAD, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout)

    async def get(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.GET, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout)

    async def post(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.POST, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout)

    async def put(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.PUT, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout)

    async def delete(
        self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.DELETE, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout)

    async def options(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.OPTIONS, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout)

    async def patch(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.PATCH, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout)

    async def trace(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.TRACE, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout)

    async def connect(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.CONNECT, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout)

    async def close(self) -> None:
        while self._conns:
            _, conn = self._conns.popitem()
            conn.transport.close()

        await asyncio.sleep(0)

        for tsk in set(self._pending_tsks):
            await tsk


async def head(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().head(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout)


async def get(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().get(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout)


async def post(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().post(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout)


async def put(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().put(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout)


async def delete(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().delete(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout)


async def options(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().options(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout)


async def patch(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().patch(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout)


async def trace(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().trace(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout)


async def connect(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().connect(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout)
