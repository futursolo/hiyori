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

from typing import Union, Dict, List, Any, Mapping

import abc
import io
import json
import urllib.parse

__all__ = [
    "BaseRequestBody",
    "BytesRequestBody",
    "UrlEncodedRequestBody",
    "ResponseBody"]


class BaseRequestBody(abc.ABC):
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
    async def read(self, n: int) -> bytes:
        """
        Read maximum n bytes or raise :class:`EOFError` if finished.
        """
        raise NotImplementedError


class BytesRequestBody(BaseRequestBody):
    def __init__(self, buf: bytes) -> None:
        self._len = len(buf)

        self._io = io.BytesIO(buf)
        self._io.seek(0, io.SEEK_SET)

    async def calc_len(self) -> int:
        return self._len

    async def seek_front(self) -> None:
        self._io.seek(0, io.SEEK_SET)

    async def read(self, n: int) -> bytes:
        data = self._io.read(n)

        if not data:
            raise EOFError

        return data


class UrlEncodedRequestBody(BytesRequestBody):
    def __init__(self, __map: Mapping[str, str]) -> None:
        super().__init__(urllib.parse.urlencode(__map).encode())


class _EmptyRequestBody(BaseRequestBody):
    async def calc_len(self) -> int:
        return 0

    async def seek_front(self) -> None:
        pass

    async def read(self, n: int) -> bytes:
        raise EOFError


EMPTY_REQUEST_BODY = _EmptyRequestBody()


class ResponseBody(bytes):
    def to_json(self) -> Union[
            Dict[str, Any], List[Any], int, str, float, bool, None]:
        return json.loads(self.to_str())  # type: ignore

    def to_str(self, encoding: str="utf-8") -> str:
        return self.decode(encoding)


EMPTY_RESPONSE_BODY = ResponseBody()
