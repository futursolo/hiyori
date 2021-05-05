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

from typing import Mapping, Optional, Union
import contextlib
import urllib.parse
import warnings

import magicdict
import magichttp

from . import _version, bodies, connection, constants

__all__ = ["PendingRequest", "Request", "Response"]

_SELF_IDENTIFIER = "hiyori/{} magichttp/{}".format(
    _version.__version__, magichttp.__version__
)


class PendingRequest:
    def __init__(
        self,
        __method: constants.HttpRequestMethod,
        *,
        authority: str,
        path: str = "/",
        path_args: Optional[Mapping[str, str]] = None,
        scheme: Union[str, constants.HttpScheme] = constants.HttpScheme.HTTP,
        headers: Optional[Mapping[str, str]] = None,
        version: constants.HttpVersion = constants.HttpVersion.V1_1,
        body: Optional[Union[bytes, bodies.BaseRequestBody]] = None,
    ) -> None:
        assert (
            path.find("?") == -1
        ), "Please pass path arguments using path_args keyword argument."

        self._method = __method
        self._version = version

        self._authority = authority

        if isinstance(scheme, str):
            self._scheme = constants.HttpScheme(scheme.lower())

        else:
            self._scheme = scheme

        self._path = path
        self._path_args = path_args

        self._headers: magicdict.TolerantMagicDict[
            str, str
        ] = magicdict.TolerantMagicDict(headers or {})
        self._headers.setdefault("user-agent", _SELF_IDENTIFIER)

        self._cached_uri: Optional[str] = None

        self._body: bodies.BaseRequestBody
        if isinstance(body, bytes):
            self._body = bodies.BytesRequestBody(body)

        else:
            self._body = body or bodies.EMPTY_REQUEST_BODY

    @property
    def method(self) -> constants.HttpRequestMethod:
        return self._method

    @property
    def version(self) -> constants.HttpVersion:
        return self._version

    @property
    def uri(self) -> str:
        if self._cached_uri is None:
            self._cached_uri = self._path

            if self._path_args:
                self._cached_uri += "?" + urllib.parse.urlencode(
                    self._path_args
                )

        return self._cached_uri

    @property
    def authority(self) -> str:
        return self._authority

    @property
    def scheme(self) -> constants.HttpScheme:
        return self._scheme

    @property
    def headers(self) -> magicdict.TolerantMagicDict[str, str]:
        return self._headers

    @property
    def body(self) -> bodies.BaseRequestBody:
        return self._body

    @property
    def conn_id(self) -> "connection.HttpConnectionId":
        return connection.HttpConnectionId(
            http_version=self.version,
            authority=self.authority,
            scheme=self.scheme,
        )

    def __repr__(self) -> str:  # pragma: no cover
        parts = [
            f"method={self.method!r}",
            f"version={self.version!r}",
            f"uri={self.uri!r}",
            f"authority={self.authority!r}",
            f"scheme={self.scheme!r}",
            f"headers={self.headers!r}",
        ]

        return f"<{self.__class__.__name__} {', '.join(parts)}>"

    def __str__(self) -> str:  # pragma: no cover
        return repr(self)


class Request:
    def __init__(self, writer: magichttp.HttpRequestWriter) -> None:
        self._writer = writer

    @property
    def method(self) -> constants.HttpRequestMethod:
        return self._writer.initial.method

    @property
    def version(self) -> constants.HttpVersion:
        return self._writer.initial.version

    @property
    def uri(self) -> str:
        return self._writer.initial.uri

    @property
    def authority(self) -> str:
        return self._writer.initial.authority

    @property
    def scheme(self) -> constants.HttpScheme:
        return constants.HttpScheme(self._writer.initial.scheme.lower())

    @property
    def headers(self) -> magicdict.FrozenTolerantMagicDict[str, str]:
        return self._writer.initial.headers

    def __repr__(self) -> str:  # pragma: no cover
        parts = [
            f"method={self.method!r}",
            f"version={self.version!r}",
            f"uri={self.uri!r}",
        ]

        with contextlib.suppress(AttributeError):
            parts.append(f"authority={self.authority!r}")

        with contextlib.suppress(AttributeError):
            parts.append(f"scheme={self.scheme!r}")

        parts.append(f"headers={self.headers!r}")

        return f"<{self.__class__.__name__} {', '.join(parts)}>"

    def __str__(self) -> str:  # pragma: no cover
        return repr(self)


class Response:
    def __init__(
        self,
        request: Request,
        reader: magichttp.HttpResponseReader,
        conn: "connection.HttpConnection",
        body: Optional[bytes] = None,
    ) -> None:
        self._request = request

        self._reader = reader
        self._conn = conn

        self._body = (
            bodies.ResponseBody(body) if body else bodies.EMPTY_RESPONSE_BODY
        )

    @property
    def request(self) -> Request:
        return self._request

    @property
    def status_code(self) -> constants.HttpStatusCode:
        return self._reader.initial.status_code

    @property
    def version(self) -> constants.HttpVersion:
        return self._reader.initial.version

    @property
    def headers(self) -> magicdict.FrozenTolerantMagicDict[str, str]:
        return self._reader.initial.headers

    @property
    def reader(self) -> magichttp.HttpResponseReader:
        return self._reader

    @property
    def body(self) -> bodies.ResponseBody:
        return self._body

    def __repr__(self) -> str:  # pragma: no cover
        parts = [
            f"request={self.request!r}",
            f"status_code={self.status_code!r}",
            f"version={self.version!r}",
            f"headers={self.headers!r}",
        ]

        return f"<{self.__class__.__name__} {', '.join(parts)}>"

    def __str__(self) -> str:  # pragma: no cover
        return repr(self)

    def __del__(self) -> None:
        if not self._reader.finished():
            warnings.warn(
                "Response body is not being properly retrieved. "
                "Please read till the end."
            )

            self.reader.abort()
