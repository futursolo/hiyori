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

import asyncio
import os

from test_helper import MockServer, helper
import helpers
import pytest

from hiyori import (
    BadResponse,
    ConnectionClosed,
    FailedRedirection,
    HttpClient,
    HttpError,
    HttpRequestMethod,
    HttpVersion,
    ResponseEntityTooLarge,
    TooManyRedirects,
    get,
)


class GetEchoProtocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)
        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!"
        )


class GetEchoServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!"
        )


class JsonResponseServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b'HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n{"a": "b"}'
        )


class AlwaysRedirectServer(MockServer):
    def data_received(self, data):
        super().data_received(data)

        self.transport.write(
            b"HTTP/1.1 302 Found\r\nLocation: /\r\n"
            b"Content-Length: 0\r\n\r\n"
        )


class Redirect10TimesServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        for _ in range(0, 10):
            transport.write(
                b"HTTP/1.1 302 Found\r\nLocation: /\r\n"
                b"Content-Length: 0\r\n\r\n"
            )

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!"
        )


class RelativeRedirectServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 302 Found\r\nLocation: ../\r\n"
            b"Content-Length: 0\r\n\r\n"
        )

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!"
        )


class Http404Server(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 19\r\n\r\n"
            b"HTTP 404: Not Found"
        )


class ConnectionClosedServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello,")
        transport.close()


class UrandomServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(os.urandom(128 * 1024))


class MalformedServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.2 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!"
        )


@pytest.mark.asyncio
async def test_simple(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = GetEchoProtocol

    response = await get(f"http://localhost:{mocked_server.port}")

    assert response.status_code == 200
    assert response.body == b"Hello, World!"
    assert response.version == HttpVersion.V1_1
    assert response.headers == {"content-length": "13"}

    assert response.request.method == HttpRequestMethod.GET
    assert response.request.version == HttpVersion.V1_1
    assert response.request.uri == "/"
    assert response.request.authority == f"localhost:{mocked_server.port}"
    assert not hasattr(response.request, "scheme")
    assert response.request.headers == {
        "user-agent": helper.get_version_str(),
        "accept": "*/*",
        "host": f"localhost:{mocked_server.port}",
    }

    mocked_server.select_proto().assert_initial(
        b"GET / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Accept: */*",
        f"Host: localhost:{mocked_server.port}".encode(),
    )


@pytest.mark.asyncio
async def test_simple_unix(
    mocked_unix_server: helpers.MockedUnixServer,
) -> None:
    mocked_unix_server.mock_proto_cls = GetEchoProtocol

    client = HttpClient()
    client.resolver.override(
        "localhost",
        mocked_unix_server.port,
        resolve_to=mocked_unix_server.path,
    )

    response = await client.get(f"http://localhost:{mocked_unix_server.port}")

    assert response.status_code == 200
    assert response.body == b"Hello, World!"
    assert response.version == HttpVersion.V1_1
    assert response.headers == {"content-length": "13"}

    assert response.request.method == HttpRequestMethod.GET
    assert response.request.version == HttpVersion.V1_1
    assert response.request.uri == "/"
    assert response.request.authority == f"localhost:{mocked_unix_server.port}"
    assert not hasattr(response.request, "scheme")
    assert response.request.headers == {
        "user-agent": helper.get_version_str(),
        "accept": "*/*",
        "host": f"localhost:{mocked_unix_server.port}",
    }

    mocked_unix_server.select_proto().assert_initial(
        b"GET / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Accept: */*",
        f"Host: localhost:{mocked_unix_server.port}".encode(),
    )


class GetTestCase:
    @helper.run_async_test(with_srv_cls=GetEchoServer)
    async def test_simple(self):
        response = await get("http://localhost:8000")

        assert response.status_code == 200
        assert response.body == b"Hello, World!"
        assert response.version == HttpVersion.V1_1
        assert response.headers == {"content-length": "13"}

        assert response.request.method == HttpRequestMethod.GET
        assert response.request.version == HttpVersion.V1_1
        assert response.request.uri == "/"
        assert response.request.authority == "localhost:8000"
        assert not hasattr(response.request, "scheme")
        assert response.request.headers == {
            "user-agent": helper.get_version_str(),
            "accept": "*/*",
            "host": "localhost:8000",
        }

        helper.assert_initial_bytes(
            b"".join(helper.mock_srv.data_chunks),
            b"GET / HTTP/1.1",
            b"User-Agent: %(self_ver_bytes)s",
            b"Accept: */*",
            b"Host: localhost:8000",
        )

    @helper.run_async_test(with_srv_cls=JsonResponseServer)
    async def test_json(self):
        async with HttpClient() as client:
            response = await client.get("http://localhost:8000")

            assert response.status_code == 200
            assert response.body.to_json() == {"a": "b"}

            helper.assert_initial_bytes(
                b"".join(helper.mock_srv.data_chunks),
                b"GET / HTTP/1.1",
                b"User-Agent: %(self_ver_bytes)s",
                b"Accept: */*",
                b"Host: localhost:8000",
            )

    @helper.run_async_test(with_srv_cls=GetEchoServer)
    async def test_path_args(self):
        async with HttpClient() as client:
            response = await client.get(
                "http://localhost:8000/?a=b", path_args={"c": "d"}
            )

            assert response.status_code == 200
            assert response.body == b"Hello, World!"

            helper.assert_initial_bytes(
                b"".join(helper.mock_srv.data_chunks),
                b"GET /?a=b&c=d HTTP/1.1",
                b"User-Agent: %(self_ver_bytes)s",
                b"Accept: */*",
                b"Host: localhost:8000",
            )

    @helper.run_async_test(with_srv_cls=AlwaysRedirectServer)
    async def test_default_no_redirect(self):
        async with HttpClient() as client:
            response = await client.get("http://localhost:8000/")

            assert response.status_code == 302
            assert response.headers["location"] == "/"

    @helper.run_async_test(with_srv_cls=Redirect10TimesServer)
    async def test_redirect_successful(self):
        async with HttpClient() as client:
            response = await client.get(
                "http://localhost:8000/", follow_redirection=True
            )

            assert response.status_code == 200
            assert response.body == b"Hello, World!"

    @helper.run_async_test(with_srv_cls=AlwaysRedirectServer)
    async def test_too_many_redirects(self):
        async with HttpClient() as client:
            with pytest.raises(TooManyRedirects):
                await client.get(
                    "http://localhost:8000/", follow_redirection=True
                )

    @helper.run_async_test(with_srv_cls=RelativeRedirectServer)
    async def test_prevent_relative_redirect(self):
        async with HttpClient() as client:
            with pytest.raises(FailedRedirection):
                await client.get(
                    "http://localhost:8000/", follow_redirection=True
                )

    @helper.run_async_test(with_srv_cls=Http404Server)
    async def test_response_404(self):
        async with HttpClient() as client:
            with pytest.raises(HttpError) as exc_info:
                await client.get("http://localhost:8000/")

            assert exc_info.value.status_code == 404
            assert exc_info.value.status_description == "Not Found"

    @helper.run_async_test(with_srv_cls=Http404Server)
    async def test_response_404_no_raise(self):
        async with HttpClient(raise_error=False) as client:
            response = await client.get("http://localhost:8000/")

            assert response.status_code == 404
            assert response.body == b"HTTP 404: Not Found"

    @helper.run_async_test(with_srv_cls=ConnectionClosedServer)
    async def test_connection_closed(self):
        async with HttpClient() as client:
            with pytest.raises(ConnectionClosed):
                await client.get("http://localhost:8000/")

    @helper.run_async_test(with_srv_cls=GetEchoServer)
    async def test_too_large(self):
        async with HttpClient(max_body_size=12) as client:
            with pytest.raises(ResponseEntityTooLarge):
                await client.get("http://localhost:8000")

    @helper.run_async_test(with_srv_cls=UrandomServer)
    async def test_too_large_2(self):
        async with HttpClient(max_body_size=12) as client:
            with pytest.raises(ResponseEntityTooLarge):
                await client.get("http://localhost:8000")

    @helper.run_async_test(with_srv_cls=MalformedServer)
    async def test_malformed_data(self):
        async with HttpClient(max_body_size=12) as client:
            with pytest.raises(BadResponse):
                await client.get("http://localhost:8000")
