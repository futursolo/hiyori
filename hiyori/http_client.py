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

from typing import MutableMapping, Optional, Mapping, Union
from typing import Awaitable  # noqa: F401

from . import messages
from . import exceptions
from . import constants
from . import connection

import ssl
import collections
import asyncio
import urllib.parse
import magicdict
import typing
import re

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
    "trace",
    "patch"]

_ABSOLUTE_PATH_RE = re.compile("^(http:/|https:/)?/")


class HttpClient:
    def __init__(
            self, *,
            idle_timeout: int=10,
            timeout: int=60,

            max_initial_size: int=64 * 1024,  # 64K
            max_body_size: int=2 * 1024 * 1024,  # 2M
            chunk_size: int=128 * 1024,  # 128K

            allow_keep_alive: bool=True,
            tls_context: Optional[ssl.SSLContext]=None,
            max_idle_connections: int=100,
            max_redirects: int=10
            ) -> None:
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
            connection.HttpConnectionId, connection.HttpConnection] = \
            collections.OrderedDict()

        class _HttpConnection(connection.HttpConnection):
            _MAX_INITIAL_SIZE = self._max_initial_size

        self._HttpConnection = _HttpConnection

    async def _get_conn(
        self, __id: connection.HttpConnectionId, timeout: int
            )-> connection.HttpConnection:
        if __id.scheme == constants.HttpScheme.HTTPS:
            tls_context: Optional[ssl.SSLContext] = self._tls_context

        else:
            tls_context = None

        return await self._HttpConnection.connect(
            __id, timeout=timeout, tls_context=tls_context,
            chunk_size=self._chunk_size, idle_timeout=self._idle_timeout)

    async def _put_conn(self, __conn: connection.HttpConnection) -> None:
        if __conn._closing():
            await __conn._close_conn()

            return

        if self._allow_keep_alive is False:
            await __conn._close_conn()

        if __conn._conn_id in self._conns.keys():
            old_conn = self._conns.pop(__conn._conn_id)

            await old_conn._close_conn()

        self._conns[__conn._conn_id] = __conn

    async def close(self) -> None:
        while self._conns:
            _, conn = self._conns.popitem()
            await conn._close_conn()

    async def send_request(
            self, __request: messages.PendingRequest, *,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        _timeout = timeout if timeout is not None else self._timeout
        _max_redirects = max_redirects or self._max_redirects
        _max_body_size = max_body_size or self._max_body_size
        conn_id = __request.conn_id

        conn = await self._get_conn(conn_id, timeout=_timeout)

        try:
            response = await asyncio.wait_for(conn._send_request(
                __request, read_response_body=read_response_body,
                max_body_size=_max_body_size),
                _timeout)

        except asyncio.TimeoutError as e:
            await conn._close_conn()

            raise exceptions.RequestTimeout from e

        if read_response_body:
            await self._put_conn(conn)

        if follow_redirection:
            if response.status_code in (301, 302, 303, 307, 308):
                if _max_redirects == 0:
                    raise exceptions.TooManyRedirects(response.request)

                try:
                    location = response.headers["location"]

                except KeyError as e:
                    raise exceptions.BadResponse(
                        "Server asked for a redirection; "
                        "however, did not specify the location."
                    ) from e

                if _ABSOLUTE_PATH_RE.match(location) is None:
                    raise exceptions.FailedRedirection(
                        "redirection support for relative path "
                        "is not implemented.")

                if location.startswith("/"):
                    location = __request.scheme.value.lower() + "://" \
                        + __request.authority + location

                if response.status_code < 304:
                    return await self.fetch(
                        constants.HttpRequestMethod.GET,
                        location,
                        follow_redirection=True,
                        max_redirects=_max_redirects - 1,
                        timeout=_timeout)

                else:
                    body = __request.body
                    try:
                        await body.seek_front()

                    except NotImplementedError as e:
                        raise exceptions.FailedRedirection(
                            "seek_front is not implemented for"
                            " current body.") from e

                    return await self.fetch(
                        response.request.method,
                        location,
                        headers=response.request.headers,
                        body=body,
                        read_response_body=True,
                        follow_redirection=True,
                        max_redirects=_max_redirects - 1,
                        timeout=_timeout)

        return response

    async def fetch(
            self, __method: constants.HttpRequestMethod, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        parsed_url = urllib.parse.urlsplit(__url, scheme="http")

        final_path_args = magicdict.TolerantMagicDict(path_args or {})

        if parsed_url.query:
            final_path_args.update(urllib.parse.parse_qsl(parsed_url.query))

        request = messages.PendingRequest(
            __method, authority=parsed_url.netloc, path=parsed_url.path or "/",
            path_args=final_path_args, scheme=parsed_url.scheme,
            headers=headers, version=constants.HttpVersion.V1_1, body=body)

        return await self.send_request(
            request,
            read_response_body=read_response_body,
            timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size)

    async def head(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.HEAD, __url,
            path_args=path_args, headers=headers, body=None,
            read_response_body=True, timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=None)

    async def get(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.GET, __url,
            path_args=path_args, headers=headers, body=None,
            read_response_body=read_response_body, timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size)

    async def post(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.POST, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size)

    async def put(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.PUT, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size)

    async def delete(
        self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.DELETE, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size)

    async def patch(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.PATCH, __url,
            path_args=path_args, headers=headers, body=body,
            read_response_body=read_response_body, timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size)

    async def options(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.OPTIONS, __url,
            path_args=path_args, headers=headers, body=None,
            read_response_body=read_response_body, timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size)

    async def trace(
            self, __url: str,
            path_args: Optional[Mapping[str, str]]=None,
            headers: Optional[Mapping[str, str]]=None,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.TRACE, __url,
            path_args=path_args, headers=headers, body=None,
            read_response_body=read_response_body, timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size)


async def head(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        timeout: Optional[int]=None,
        follow_redirection: bool=False,
        max_redirects: Optional[int]=None,
        ) -> messages.Response:
    return await HttpClient().head(
        __url, path_args=path_args, headers=headers,
        timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects)


async def get(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None,
        follow_redirection: bool=False,
        max_redirects: Optional[int]=None,
        max_body_size: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().get(
        __url, path_args=path_args, headers=headers,
        read_response_body=read_response_body, timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size)


async def post(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None,
        follow_redirection: bool=False,
        max_redirects: Optional[int]=None,
        max_body_size: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().post(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size)


async def put(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None,
        follow_redirection: bool=False,
        max_redirects: Optional[int]=None,
        max_body_size: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().put(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size)


async def delete(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None,
        follow_redirection: bool=False,
        max_redirects: Optional[int]=None,
        max_body_size: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().delete(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size)


async def patch(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        body: Optional[Union[bytes, "bodies.BaseRequestBody"]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None,
        follow_redirection: bool=False,
        max_redirects: Optional[int]=None,
        max_body_size: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().patch(
        __url, path_args=path_args, headers=headers, body=body,
        read_response_body=read_response_body, timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size)


async def options(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None,
        follow_redirection: bool=False,
        max_redirects: Optional[int]=None,
        max_body_size: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().options(
        __url, path_args=path_args, headers=headers,
        read_response_body=read_response_body, timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size)


async def trace(
        __url: str,
        path_args: Optional[Mapping[str, str]]=None,
        headers: Optional[Mapping[str, str]]=None,
        read_response_body: bool=True,
        timeout: Optional[int]=None,
        follow_redirection: bool=False,
        max_redirects: Optional[int]=None,
        max_body_size: Optional[int]=None
        ) -> messages.Response:
    return await HttpClient().trace(
        __url, path_args=path_args, headers=headers,
        read_response_body=read_response_body, timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size)
