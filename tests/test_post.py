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

from test_helper import MockServer, helper
import pytest

from hiyori import HttpClient, HttpRequestMethod, HttpVersion, post


class PostEchoServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!"
        )


class PostTestCase:
    @helper.run_async_test(with_srv_cls=PostEchoServer)
    async def test_simple(self):
        response = await post("http://localhost:8000", body=b"1234567890")

        assert response.status_code == 200
        assert response.body == b"Hello, World!"
        assert response.version == HttpVersion.V1_1
        assert response.headers == {"content-length": "13"}

        assert response.request.method == HttpRequestMethod.POST
        assert response.request.version == HttpVersion.V1_1
        assert response.request.uri == "/"
        assert response.request.authority == "localhost:8000"
        assert not hasattr(response.request, "scheme")
        assert response.request.headers == {
            "user-agent": helper.get_version_str(),
            "content-length": "10",
            "accept": "*/*",
            "host": "localhost:8000",
        }

    @helper.run_async_test(with_srv_cls=PostEchoServer)
    async def test_urlencoded_body(self):
        async with HttpClient() as client:
            response = await client.post(
                "http://localhost:8000", body={"a": "b", "c": "d"}
            )

        assert response.request.headers == {
            "user-agent": helper.get_version_str(),
            "content-type": "application/x-www-form-urlencoded",
            "content-length": "7",
            "accept": "*/*",
            "host": "localhost:8000",
        }

        initial_bytes, body = b"".join(helper.mock_srv.data_chunks).split(
            b"\r\n\r\n", 1
        )

        helper.assert_initial_bytes(
            initial_bytes,
            b"POST / HTTP/1.1",
            b"User-Agent: %(self_ver_bytes)s",
            b"Content-Type: application/x-www-form-urlencoded",
            b"Content-Length: 7",
            b"Accept: */*",
            b"Host: localhost:8000",
        )

        assert body == b"a=b&c=d"

    @helper.run_async_test(with_srv_cls=PostEchoServer)
    async def test_json_body(self):
        async with HttpClient() as client:
            response = await client.post(
                "http://localhost:8000", json={"a": "b", "c": [1, 2]}
            )

            assert response.request.headers == {
                "user-agent": helper.get_version_str(),
                "content-type": "application/json",
                "content-length": "23",
                "accept": "*/*",
                "host": "localhost:8000",
            }

            initial_bytes, body = b"".join(helper.mock_srv.data_chunks).split(
                b"\r\n\r\n", 1
            )

            helper.assert_initial_bytes(
                initial_bytes,
                b"POST / HTTP/1.1",
                b"User-Agent: %(self_ver_bytes)s",
                b"Content-Type: application/json",
                b"Content-Length: 23",
                b"Accept: */*",
                b"Host: localhost:8000",
            )

            assert body == b'{"a": "b", "c": [1, 2]}'

    @helper.run_async_test(with_srv_cls=PostEchoServer)
    async def test_urlencoded_and_json_body(self):
        async with HttpClient() as client:
            with pytest.raises(ValueError):
                await client.post(
                    "http://localhost:8000", body={"a": "b"}, json={"c": "d"}
                )
