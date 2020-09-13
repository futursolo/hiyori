#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#   Copyright 2020 Kaede Hoshikawa
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

from hiyori import post
from hiyori.multipart import MultipartRequestBody, File

from test_helper import helper, MockServer

import io


class MultipartEchoServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!")


class MultipartTestCase:
    @helper.run_async_test(with_srv_cls=MultipartEchoServer)
    async def test_simple(self):
        await post(
            "http://localhost:8000/",
            body={"a": "b", "c": io.BytesIO(b"1234567890")})

    @helper.run_async_test
    async def test_detail(self):
        body = MultipartRequestBody({"a": "b", "c": io.BytesIO(b"1234567890")})
        boundary = body.boundary

        body_buf = bytearray()
        while True:
            try:
                body_buf += await body.read(128 * 1024)

            except EOFError:
                break

        assert body_buf == b"""\
--%(boundary)s\r
Content-Disposition: form-data; name="a"\r
\r
b\r
--%(boundary)s\r
Content-Type: application/octet-stream\r
Content-Disposition: form-data; name="c"\r
\r
1234567890--%(boundary)s--\r
""" % {b"boundary": boundary.encode()}

    @helper.run_async_test
    async def test_with_file_obj(self):
        body = MultipartRequestBody(
            {
                "a": "b",
                "c": File(
                    b"1234567890",
                    filename="abc.example",
                    content_type="x-application/example")
            }
        )
        boundary = body.boundary

        body_buf = bytearray()
        while True:
            try:
                body_buf += await body.read(128 * 1024)

            except EOFError:
                break

        assert body_buf == b"""\
--%(boundary)s\r
Content-Disposition: form-data; name="a"\r
\r
b\r
--%(boundary)s\r
Content-Type: x-application/example\r
Content-Disposition: form-data; name="c"; filename="abc.example"\r
\r
1234567890--%(boundary)s--\r
""" % {b"boundary": boundary.encode()}
