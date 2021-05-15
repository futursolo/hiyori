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

from typing import (
    Any,
    BinaryIO,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Union,
)
import asyncio
import collections
import dataclasses
import re
import ssl
import urllib.parse

import magicdict

from . import (
    bodies,
    connection,
    constants,
    exceptions,
    messages,
    multipart,
    resolvers,
)

__all__ = [
    "HttpClient",
    "fetch",
    "get",
    "post",
    "put",
    "delete",
    "head",
    "options",
    "patch",
]

_ABSOLUTE_PATH_RE = re.compile("^(http:/|https:/)?/")

_BODY = Union[
    bytes,
    bodies.BaseRequestBody,
    Dict[str, Union[str, BinaryIO, multipart.File]],
]


@dataclasses.dataclass
class _ReadLock:
    def __init__(self, client_lock: "_ClientLock") -> None:
        self._idling = asyncio.Event()
        self._idling.set()
        self._count = 0

        self._client_lock = client_lock

    async def __aenter__(self) -> None:
        await asyncio.sleep(0)

        if self._client_lock.close_lock._closing:
            raise RuntimeError("Client is closing.")

        self._count += 1
        self._idling.clear()

    async def __aexit__(self, *args: Any, **kwargs: Any) -> None:
        self._count -= 1

        if self._count == 0:
            self._idling.set()


@dataclasses.dataclass
class _CloseLock:
    def __init__(self, client_lock: "_ClientLock") -> None:
        self._closing = False

        self._client_lock = client_lock

    async def __aenter__(self) -> None:
        self._closing = True

        await self._client_lock.read_lock._idling.wait()

    async def __aexit__(self, *args: Any, **kwargs: Any) -> None:
        pass


@dataclasses.dataclass
class _ClientLock:
    def __init__(self) -> None:
        self.read_lock = _ReadLock(self)
        self.close_lock = _CloseLock(self)


class HttpClient:
    """
    Hiyori HTTP Client.

    This class holds persistent connections and tls sessions. You may want to
    use this class if you want to make multiple requests.
    """

    def __init__(
        self,
        *,
        idle_timeout: int = 10,
        timeout: int = 60,
        max_initial_size: int = 64 * 1024,  # 64K
        max_body_size: int = 2 * 1024 * 1024,  # 2M
        chunk_size: int = 128 * 1024,  # 128K
        allow_keep_alive: bool = True,
        tls_context: Optional[ssl.SSLContext] = None,
        max_idle_connections: int = 100,
        max_redirects: int = 10,
        resolver: Optional[resolvers.BaseResolver] = None,
        raise_error: bool = True,
    ) -> None:
        self._allow_keep_alive = allow_keep_alive
        self._max_initial_size = max_initial_size

        self._max_body_size = max_body_size
        self._chunk_size = chunk_size

        self._tls_context = tls_context or ssl.create_default_context(
            ssl.Purpose.CLIENT_AUTH
        )

        self._timeout = timeout
        self._idle_timeout = idle_timeout
        self._max_idle_connections = max_idle_connections

        self._max_redirects = max_redirects

        self._raise_error = raise_error

        self._conns: MutableMapping[
            connection.HttpConnectionId, connection.HttpConnection
        ] = collections.OrderedDict()

        self._resolver = resolver or resolvers.DefaultResolver()

        self._lock = _ClientLock()

    @property
    def resolver(self) -> resolvers.BaseResolver:
        return self._resolver

    async def _get_conn(
        self, __id: connection.HttpConnectionId, timeout: int
    ) -> connection.HttpConnection:
        if __id in self._conns:
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
            __id,
            max_initial_size=self._max_initial_size,
            tls_context=tls_context,
            chunk_size=self._chunk_size,
            idle_timeout=self._idle_timeout,
            resolver=self._resolver,
        )

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
        async with self._lock.close_lock:
            tasks: List["asyncio.Task[None]"] = []

            loop = asyncio.get_event_loop()

            while self._conns:
                _, conn = self._conns.popitem()
                conn.close()
                tasks.append(loop.create_task(conn.wait_closed()))

            if tasks:
                await asyncio.wait(tasks)

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *args: Any, **kwargs: Any) -> None:
        await self.close()

    async def _handle_redirection(
        self,
        __request: messages.PendingRequest,
        *,
        read_response_body: bool,
        timeout: Optional[int],
        max_redirects: Optional[int],
        max_body_size: Optional[int],
        raise_error: Optional[bool],
    ) -> messages.Response:
        if max_redirects is None:
            _max_redirects = self._max_redirects

        else:
            _max_redirects = max_redirects

        for i in range(0, _max_redirects + 1):
            if i == 0:
                response = await self.send_request(
                    __request,
                    read_response_body=read_response_body,
                    timeout=timeout,
                    follow_redirection=False,
                    max_body_size=max_body_size,
                    raise_error=raise_error,
                )

            else:
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
                        "is not implemented."
                    )

                if location.startswith("/"):
                    location = (
                        __request.scheme.value.lower()
                        + "://"
                        + __request.authority
                        + location
                    )

                if response.status_code < 304:
                    method = constants.HttpRequestMethod.GET
                    body: Optional[bodies.BaseRequestBody] = None
                    headers: Optional[Mapping[str, str]] = None

                else:
                    method = __request.method
                    body = __request.body
                    try:
                        await body.seek_front()

                    except NotImplementedError as e:
                        raise exceptions.FailedRedirection(
                            "seek_front is not implemented for"
                            " current body."
                        ) from e
                    headers = __request.headers

                response = await self.fetch(
                    method,
                    location,
                    headers=headers,
                    body=body,
                    read_response_body=read_response_body,
                    timeout=timeout,
                    raise_error=raise_error,
                )

            if response.status_code not in (301, 302, 303, 307, 308):
                return response

        else:
            raise exceptions.TooManyRedirects(response.request)

    async def send_request(
        self,
        __request: messages.PendingRequest,
        *,
        read_response_body: bool = True,
        timeout: Optional[int] = None,
        follow_redirection: bool = False,
        max_redirects: Optional[int] = None,
        max_body_size: Optional[int] = None,
        raise_error: Optional[bool] = None,
    ) -> messages.Response:
        if follow_redirection:
            return await self._handle_redirection(
                __request,
                read_response_body=read_response_body,
                timeout=timeout,
                max_redirects=max_redirects,
                max_body_size=max_body_size,
                raise_error=raise_error,
            )

        async with self._lock.read_lock:
            _timeout = timeout if timeout is not None else self._timeout
            _max_body_size = (
                max_body_size
                if max_body_size is not None
                else self._max_body_size
            )
            _raise_error = (
                raise_error if raise_error is not None else self._raise_error
            )

            conn = await self._get_conn(__request.conn_id, timeout=_timeout)

            try:
                response = await asyncio.wait_for(
                    conn.send_request(
                        __request,
                        read_response_body=read_response_body,
                        max_body_size=_max_body_size,
                    ),
                    _timeout,
                )

            except asyncio.TimeoutError as e:
                conn.close()
                await conn.wait_closed()

                raise exceptions.RequestTimeout from e

            except Exception:
                conn.close()
                await conn.wait_closed()

                raise

            if read_response_body:
                await self._put_conn(conn)

            if _raise_error and response.status_code >= 400:
                raise exceptions.HttpError(response)

            return response

    async def fetch(
        self,
        __method: constants.HttpRequestMethod,
        __url: str,
        path_args: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        body: Optional[_BODY] = None,
        json: Optional[Any] = None,
        read_response_body: bool = True,
        timeout: Optional[int] = None,
        follow_redirection: bool = False,
        max_redirects: Optional[int] = None,
        max_body_size: Optional[int] = None,
        raise_error: Optional[bool] = None,
    ) -> messages.Response:
        async with self._lock.read_lock:
            if None not in (body, json):
                raise ValueError(
                    "You cannot supply both body and json argument."
                )

            parsed_url = urllib.parse.urlsplit(__url, scheme="http")
            final_path_args: magicdict.TolerantMagicDict[
                str, str
            ] = magicdict.TolerantMagicDict()

            if parsed_url.query:
                final_path_args.update(
                    urllib.parse.parse_qsl(parsed_url.query)
                )

            if path_args:
                final_path_args.update(path_args)

            if isinstance(body, dict):
                for v in body.values():
                    if not isinstance(v, str):
                        body = multipart.MultipartRequestBody(body)
                        content_type: Optional[str] = body.content_type

                        break
                else:
                    body = bodies.UrlEncodedRequestBody(body)  # type: ignore
                    content_type = "application/x-www-form-urlencoded"

            elif json is not None:
                body = bodies.JsonRequestBody(json)
                content_type = "application/json"

            else:
                content_type = None

            request = messages.PendingRequest(
                __method,
                authority=parsed_url.netloc,
                path=parsed_url.path or "/",
                path_args=final_path_args,
                scheme=parsed_url.scheme,
                headers=headers,
                version=constants.HttpVersion.V1_1,
                body=body,
            )

            if content_type:
                request.headers["content-type"] = content_type

            return await self.send_request(
                request,
                read_response_body=read_response_body,
                timeout=timeout,
                follow_redirection=follow_redirection,
                max_redirects=max_redirects,
                max_body_size=max_body_size,
                raise_error=raise_error,
            )

    async def head(
        self,
        __url: str,
        path_args: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[int] = None,
        follow_redirection: bool = False,
        max_redirects: Optional[int] = None,
        raise_error: Optional[bool] = None,
    ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.HEAD,
            __url,
            path_args=path_args,
            headers=headers,
            timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            raise_error=raise_error,
        )

    async def get(
        self,
        __url: str,
        path_args: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        read_response_body: bool = True,
        timeout: Optional[int] = None,
        follow_redirection: bool = False,
        max_redirects: Optional[int] = None,
        max_body_size: Optional[int] = None,
        raise_error: Optional[bool] = None,
    ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.GET,
            __url,
            path_args=path_args,
            headers=headers,
            read_response_body=read_response_body,
            timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size,
            raise_error=raise_error,
        )

    async def post(
        self,
        __url: str,
        path_args: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        body: Optional[_BODY] = None,
        json: Optional[Any] = None,
        read_response_body: bool = True,
        timeout: Optional[int] = None,
        follow_redirection: bool = False,
        max_redirects: Optional[int] = None,
        max_body_size: Optional[int] = None,
        raise_error: Optional[bool] = None,
    ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.POST,
            __url,
            path_args=path_args,
            headers=headers,
            body=body,
            json=json,
            read_response_body=read_response_body,
            timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size,
            raise_error=raise_error,
        )

    async def put(
        self,
        __url: str,
        path_args: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        body: Optional[_BODY] = None,
        json: Optional[Any] = None,
        read_response_body: bool = True,
        timeout: Optional[int] = None,
        follow_redirection: bool = False,
        max_redirects: Optional[int] = None,
        max_body_size: Optional[int] = None,
        raise_error: Optional[bool] = None,
    ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.PUT,
            __url,
            path_args=path_args,
            headers=headers,
            body=body,
            json=json,
            read_response_body=read_response_body,
            timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size,
            raise_error=raise_error,
        )

    async def delete(
        self,
        __url: str,
        path_args: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        body: Optional[_BODY] = None,
        json: Optional[Any] = None,
        read_response_body: bool = True,
        timeout: Optional[int] = None,
        follow_redirection: bool = False,
        max_redirects: Optional[int] = None,
        max_body_size: Optional[int] = None,
        raise_error: Optional[bool] = None,
    ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.DELETE,
            __url,
            path_args=path_args,
            headers=headers,
            body=body,
            json=json,
            read_response_body=read_response_body,
            timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size,
            raise_error=raise_error,
        )

    async def patch(
        self,
        __url: str,
        path_args: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        body: Optional[_BODY] = None,
        json: Optional[Any] = None,
        read_response_body: bool = True,
        timeout: Optional[int] = None,
        follow_redirection: bool = False,
        max_redirects: Optional[int] = None,
        max_body_size: Optional[int] = None,
        raise_error: Optional[bool] = None,
    ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.PATCH,
            __url,
            path_args=path_args,
            headers=headers,
            body=body,
            json=json,
            read_response_body=read_response_body,
            timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size,
            raise_error=raise_error,
        )

    async def options(
        self,
        __url: str,
        path_args: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        read_response_body: bool = True,
        timeout: Optional[int] = None,
        follow_redirection: bool = False,
        max_redirects: Optional[int] = None,
        max_body_size: Optional[int] = None,
        raise_error: Optional[bool] = None,
    ) -> messages.Response:
        return await self.fetch(
            constants.HttpRequestMethod.OPTIONS,
            __url,
            path_args=path_args,
            headers=headers,
            read_response_body=read_response_body,
            timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size,
            raise_error=raise_error,
        )


async def fetch(
    __method: constants.HttpRequestMethod,
    __url: str,
    path_args: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    body: Optional[_BODY] = None,
    json: Optional[Any] = None,
    read_response_body: bool = True,
    timeout: Optional[int] = None,
    follow_redirection: bool = False,
    max_redirects: Optional[int] = None,
    max_body_size: Optional[int] = None,
    raise_error: Optional[bool] = None,
) -> messages.Response:
    async with HttpClient() as client:
        return await client.fetch(
            __method,
            __url,
            path_args=path_args,
            headers=headers,
            body=body,
            json=json,
            read_response_body=read_response_body,
            timeout=timeout,
            follow_redirection=follow_redirection,
            max_redirects=max_redirects,
            max_body_size=max_body_size,
            raise_error=raise_error,
        )


async def head(
    __url: str,
    path_args: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: Optional[int] = None,
    follow_redirection: bool = False,
    max_redirects: Optional[int] = None,
    raise_error: Optional[bool] = None,
) -> messages.Response:
    return await fetch(
        constants.HttpRequestMethod.HEAD,
        __url,
        path_args=path_args,
        headers=headers,
        timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        raise_error=raise_error,
    )


async def get(
    __url: str,
    path_args: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    read_response_body: bool = True,
    timeout: Optional[int] = None,
    follow_redirection: bool = False,
    max_redirects: Optional[int] = None,
    max_body_size: Optional[int] = None,
    raise_error: Optional[bool] = None,
) -> messages.Response:
    return await fetch(
        constants.HttpRequestMethod.GET,
        __url,
        path_args=path_args,
        headers=headers,
        read_response_body=read_response_body,
        timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size,
        raise_error=raise_error,
    )


async def post(
    __url: str,
    path_args: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    body: Optional[_BODY] = None,
    json: Optional[Any] = None,
    read_response_body: bool = True,
    timeout: Optional[int] = None,
    follow_redirection: bool = False,
    max_redirects: Optional[int] = None,
    max_body_size: Optional[int] = None,
    raise_error: Optional[bool] = None,
) -> messages.Response:
    return await fetch(
        constants.HttpRequestMethod.POST,
        __url,
        path_args=path_args,
        headers=headers,
        body=body,
        json=json,
        read_response_body=read_response_body,
        timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size,
        raise_error=raise_error,
    )


async def put(
    __url: str,
    path_args: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    body: Optional[_BODY] = None,
    json: Optional[Any] = None,
    read_response_body: bool = True,
    timeout: Optional[int] = None,
    follow_redirection: bool = False,
    max_redirects: Optional[int] = None,
    max_body_size: Optional[int] = None,
    raise_error: Optional[bool] = None,
) -> messages.Response:
    return await fetch(
        constants.HttpRequestMethod.PUT,
        __url,
        path_args=path_args,
        headers=headers,
        body=body,
        json=json,
        read_response_body=read_response_body,
        timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size,
        raise_error=raise_error,
    )


async def delete(
    __url: str,
    path_args: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    body: Optional[_BODY] = None,
    json: Optional[Any] = None,
    read_response_body: bool = True,
    timeout: Optional[int] = None,
    follow_redirection: bool = False,
    max_redirects: Optional[int] = None,
    max_body_size: Optional[int] = None,
    raise_error: Optional[bool] = None,
) -> messages.Response:
    return await fetch(
        constants.HttpRequestMethod.DELETE,
        __url,
        path_args=path_args,
        headers=headers,
        body=body,
        json=json,
        read_response_body=read_response_body,
        timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size,
        raise_error=raise_error,
    )


async def patch(
    __url: str,
    path_args: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    body: Optional[_BODY] = None,
    json: Optional[Any] = None,
    read_response_body: bool = True,
    timeout: Optional[int] = None,
    follow_redirection: bool = False,
    max_redirects: Optional[int] = None,
    max_body_size: Optional[int] = None,
    raise_error: Optional[bool] = None,
) -> messages.Response:
    return await fetch(
        constants.HttpRequestMethod.PATCH,
        __url,
        path_args=path_args,
        headers=headers,
        body=body,
        json=json,
        read_response_body=read_response_body,
        timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size,
        raise_error=raise_error,
    )


async def options(
    __url: str,
    path_args: Optional[Mapping[str, str]] = None,
    headers: Optional[Mapping[str, str]] = None,
    read_response_body: bool = True,
    timeout: Optional[int] = None,
    follow_redirection: bool = False,
    max_redirects: Optional[int] = None,
    max_body_size: Optional[int] = None,
    raise_error: Optional[bool] = None,
) -> messages.Response:
    return await fetch(
        constants.HttpRequestMethod.OPTIONS,
        __url,
        path_args=path_args,
        headers=headers,
        read_response_body=read_response_body,
        timeout=timeout,
        follow_redirection=follow_redirection,
        max_redirects=max_redirects,
        max_body_size=max_body_size,
        raise_error=raise_error,
    )
