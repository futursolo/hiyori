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

from hiyori import HttpClient

from test_helper import TestHelper, MockServer

helper = TestHelper()


class GetEchoServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!")

    def connection_lost(self, exc):
        super().connection_lost(exc)


class GetTestCase:
    @helper.run_async_test
    @helper.with_server(GetEchoServer)
    async def test_simple(self):
        async with HttpClient() as client:
            response = await client.get("http://localhost:8000")

            assert response.status_code == 200
            assert response.body == b"Hello, World!"

            helper.assert_initial_bytes(
                b"".join(helper.mock_srv.data_chunks),
                b"GET / HTTP/1.1",
                b"User-Agent: %(self_ver_bytes)s",
                b"Accept: */*",
                b"Host: localhost:8000")
