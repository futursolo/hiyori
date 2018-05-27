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

from typing import Optional, Mapping, Union

from . import constants
from . import _version

import urllib.parse
import json
import abc
import io
import magicdict
import magichttp

__all__ = [
    "BasePendingRequestBody",
    "BytesPendingRequestBody",
    "PendingRequest",

    "ResponseBody",
    "Response"]

_SELF_IDENTIFIER = "hiyori/{} magichttp/{}".format(
    _version.__version__, magichttp.__version__)


class BasePendingRequestBody(abc.ABC):
    async def calc_len(self) -> int:
        """
        Implementation of this method is optional; however,
        implementing this method will tell the server content length or
        the body has to be sent by chunked transfer encoding.
        """
        raise NotImplementedError

    async def seek_front(self) -> None:
        """
        Implementation of this method is optional; however,
        implementing this method would be helpful on handling 307 and 308
        redirections.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def read(self, n: int=126 * 1024) -> bytes:  # 128K
        """
        Read maximum n bytes or raise :class:`EOFError` if finished.
        """
        raise NotImplementedError


class BytesPendingRequestBody(BasePendingRequestBody):
    def __init__(self, buf: bytes) -> None:
        self._len = len(buf)

        self._io = io.BytesIO(buf)
        self._io.seek(0, io.SEEK_SET)

    async def calc_len(self) -> int:
        return self._len

    async def seek_front(self) -> None:
        self._io.seek(0, io.SEEK_SET)

    async def read(self, n: int=128 * 1024) -> bytes:
        data = self._io.read(n)

        if not data:
            raise EOFError

        return data


class _EmptyPendingRequestBody(BasePendingRequestBody):
    async def calc_len(self) -> int:
        return 0

    async def seek_front(self) -> None:
        pass

    async def read(self, n: int=128 * 1024) -> bytes:
        raise EOFError


_EMPTY_REQUEST_BODY = _EmptyPendingRequestBody()


class PendingRequest:
    def __init__(
        self, __method: constants.HttpRequestMethod, *,
        authority: str, path: str="/",
        path_args: Optional[Mapping[str, str]]=None,
        scheme: Optional[str]=None,
        headers: Optional[Mapping[str, str]]=None,
        version: constants.HttpVersion=constants.HttpVersion.V1_1,
            body: Optional[Union[bytes, BasePendingRequestBody]]=None) -> None:
        assert path.find("?") == -1, \
            "Please pass path arguments using path_args keyword argument."

        self._method = __method
        self._version = version

        self._authority = authority
        self._scheme = constants.HttpScheme(scheme.lower()) \
            if scheme else constants.HttpScheme.HTTP

        self._path = path
        self._path_args = path_args

        self._headers: magicdict.TolerantMagicDict[str, str] = \
            magicdict.TolerantMagicDict(headers or {})
        self._headers.setdefault("user-agent", _SELF_IDENTIFIER)

        self._cached_uri: Optional[str] = None

        self._body: BasePendingRequestBody
        if isinstance(body, bytes):
            self._body = BytesPendingRequestBody(body)

        else:
            self._body = body or _EMPTY_REQUEST_BODY

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
                self._cached_uri += "?" + \
                    urllib.parse.urlencode(self._path_args)

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
    def body(self) -> BasePendingRequestBody:
        return self._body

    def __repr__(self) -> str:
        parts = [
            f"method={self.method!r}",
            f"version={self.version!r}",
            f"uri={self.uri!r}",
            f"authority={self.authority!r}",
            f"scheme={self.scheme!r}",
            f"headers={self.headers!r}",
            f"body={self.body!r}"]

        return f"<{self.__class__.__name__} {', '.join(parts)}>"

    def __str__(self) -> str:
        return repr(self)


class ResponseBody(bytes):
    def as_json(self) -> Union[dict, list, int, str, float, bool, None]:
        return json.loads(self.decode("utf-8"))


_EMPTY_RESPONSE_BODY = ResponseBody()


class Request:
    def __init__(self, writer: magichttp.HttpRequestWriter) -> None:
        self._writer = writer

    @property
    def method(self) -> "constants.HttpRequestMethod":
        return self._writer.initial.method

    @property
    def version(self) -> "constants.HttpVersion":
        return self._writer.initial.version

    @property
    def uri(self) -> str:
        return self._writer.initial.uri

    @property
    def authority(self) -> str:
        return self._writer.initial.authority

    @property
    def scheme(self) -> str:
        return self._writer.initial.scheme

    @property
    def headers(self) -> "magicdict.FrozenTolerantMagicDict[str, str]":
        return self._writer.initial.headers

    @property
    def writer(self) -> magichttp.HttpRequestWriter:
        return self._writer


class Response:
    def __init__(
        self, request: Request,
        reader: magichttp.HttpResponseReader,
            body: Optional[bytes]=None) -> None:
        self._request = request

        self._reader = reader

        self._body = ResponseBody(body) if body else _EMPTY_RESPONSE_BODY

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
    def headers(self) -> "magicdict.FrozenTolerantMagicDict[str, str]":
        return self._reader.initial.headers

    @property
    def reader(self) -> magichttp.HttpResponseReader:
        return self._reader

    @property
    def body(self) -> ResponseBody:
        return self._body
