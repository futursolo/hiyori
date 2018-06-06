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

    async def _get_conn(
        self, __id: connection.HttpConnectionId, timeout: int
            )-> connection.HttpConnection:
        if __id in self._conns.keys():
            conn = self._conns.pop(__id)

            if not conn.closing():
                return conn

            conn.close()
            await conn.wait_closed()

        if __id.scheme == constants.HttpScheme.HTTPS:
            tls_context: Optional[ssl.SSLContext] = self._tls_context

        else:
            tls_context = None

        return connection.HttpConnection(
            __id, max_initial_size=self._max_initial_size,
            tls_context=tls_context, chunk_size=self._chunk_size,
            idle_timeout=self._idle_timeout)

    async def _put_conn(self, __conn: connection.HttpConnection) -> None:
        if __conn.closing() or self._allow_keep_alive is False:
            __conn.close()
            await __conn.wait_closed()

            return

        if __conn.conn_id not in self._conns.keys():
            self._conns[__conn.conn_id] = __conn

            return

        __conn.close()
        await __conn.wait_closed()

    async def close(self) -> None:
        while self._conns:
            _, conn = self._conns.popitem()
            conn.close()
            await conn.wait_closed()

    async def send_request(
            self, __request: messages.PendingRequest, *,
            read_response_body: bool=True,
            timeout: Optional[int]=None,
            follow_redirection: bool=False,
            max_redirects: Optional[int]=None,
            max_body_size: Optional[int]=None
            ) -> messages.Response:
        _timeout = timeout if timeout is not None else self._timeout
        _max_body_size = max_body_size or self._max_body_size

        conn = await self._get_conn(__request.conn_id, timeout=_timeout)

        try:
            response = await asyncio.wait_for(conn.send_request(
                __request, read_response_body=read_response_body,
                max_body_size=_max_body_size),
                _timeout)

        except asyncio.TimeoutError as e:
            conn.close()
            await conn.wait_closed()

            raise exceptions.RequestTimeout from e

        if read_response_body:
            await self._put_conn(conn)

        if not follow_redirection or \
                response.status_code not in (301, 302, 303, 307, 308):
            return response

        if max_redirects is None:
            _max_redirects = self._max_redirects

        else:
            _max_redirects = max_redirects

        if _max_redirects == 0:
            raise exceptions.TooManyRedirects(response.request)

        _max_redirects -= 1

        try:
            location = response.headers["location"]

        except KeyError as e:
            raise exceptions.BadResponse(
                "Server asked for a redirection; "
                "however, did not specify the location."
            ) from e

        if _ABSOLUTE_PATH_RE.match(location) is None:
            raise exceptions.FailedRedirection(
                "Redirection support for relative path "
                "is not implemented.")

        if location.startswith("/"):
            location = __request.scheme.value.lower() + "://" \
                + __request.authority + location

        if response.status_code < 304:
            return await self.fetch(
                constants.HttpRequestMethod.GET,
                location,
                follow_redirection=True,
                max_redirects=_max_redirects,
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
                read_response_body=read_response_body,
                follow_redirection=True,
                max_redirects=_max_redirects,
                timeout=_timeout)

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
