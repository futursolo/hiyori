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

from typing import Dict, Union, BinaryIO, List, Optional, Mapping

from . import bodies

import uuid
import io
import mimetypes
import magicdict
import asyncio

__all__ = ["File", "MultipartRequestBody"]


class _StrField(bodies.BytesRequestBody):
    def __init__(self, name: str, value: str, prefix: bytes) -> None:
        buf = bytearray(prefix)

        buf += "Content-Disposition: form-data; name=\"{}\"\r\n\r\n".format(
            name).encode("utf-8")
        buf += value.encode("utf-8")
        buf += b"\r\n"

        super().__init__(bytes(buf))


class _FileField(bodies.BaseRequestBody):
    pass


class File:
    def __init__(
        self, __fp: Union[BinaryIO, bytes],

        filename: Optional[str]=None,
        content_type: Optional[str]=None,
            headers: Optional[Mapping[str, str]]=None) -> None:
        if isinstance(__fp, bytes):
            self._fp: BinaryIO = io.BytesIO(__fp)

        else:
            self._fp = __fp

        self._filename = filename

        if not content_type:
            if not self._filename:
                self._content_type = "application/octet-stream"

            else:
                guess_result = mimetypes.guess_type(self._filename)

                if guess_result[0] is None:
                    self._content_type = "application/octet-stream"

                else:
                    self._content_type = guess_result[0]

        self._headers = magicdict.TolerantMagicDict(headers or {})

    def _to_file_field(self, name: str, prefix: bytes) -> _FileField:
        raise NotImplementedError


class MultipartRequestBody(bodies.BaseRequestBody):
    def __init__(
            self, form_dict: Dict[str, Union[str, BinaryIO, File]]) -> None:
        self._boundary = "--------HiyoriFormBoundary" + str(uuid.uuid4())

        field_prefix = b"--" + self._boundary.encode("ascii") + b"\r\n"
        self._affix = b"--" + self._boundary.encode("ascii") + b"--\r\n"

        self._fields: List[bodies.BaseRequestBody] = []

        for name, value in form_dict.items():
            if isinstance(value, str):
                self._fields.append(_StrField(name, value, field_prefix))

            elif isinstance(value, File):
                self._fields.append(value._to_file_field(name, field_prefix))

            else:
                raise NotImplementedError

        self._body_len: Optional[int] = None
        self._ptr = 0

        self._lock = asyncio.Lock()

    @property
    def boundary(self) -> str:
        return self._boundary

    @property
    def content_type(self) -> str:
        return "multipart/form-data; boundary=" + self.boundary

    async def calc_len(self) -> int:
        async with self._lock:
            if self._body_len is None:
                field_len = 0

                for field in self._fields:
                    field_len += await field.calc_len()

                self._body_len = field_len + len(self._affix)

            return self._body_len

    async def seek_front(self) -> None:
        async with self._lock:
            self._ptr = 0

            for field in self._fields:
                await field.seek_front()

    async def read(self, n: int) -> bytes:
        async with self._lock:
            if self._ptr >= 0:
                while True:
                    try:
                        field = self._fields[self._ptr]

                    except IndexError:
                        self._ptr = -1

                        break

                    try:
                        return await field.read(n)

                    except EOFError:
                        self._ptr += 1

            affix_pos = -self._ptr - 1

            if affix_pos >= len(self._affix):
                raise EOFError

            affix_part = self._affix[affix_pos:n]
            self._ptr -= len(affix_part)

            return affix_part
