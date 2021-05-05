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


class JsonResponseProtocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)

        transport.write(
            b'HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n{"a": "b"}'
        )


class AlwaysRedirectProtocol(helpers.BaseMockProtocol):
    def data_received(self, data: bytes) -> None:
        super().data_received(data)

        assert isinstance(self.transport, asyncio.Transport)
        self.transport.write(
            b"HTTP/1.1 302 Found\r\nLocation: /\r\n"
            b"Content-Length: 0\r\n\r\n"
        )


class Redirect10TimesProtocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)
        for _ in range(0, 10):
            transport.write(
                b"HTTP/1.1 302 Found\r\nLocation: /\r\n"
                b"Content-Length: 0\r\n\r\n"
            )

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!"
        )


class RelativeRedirectProtocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)
        transport.write(
            b"HTTP/1.1 302 Found\r\nLocation: ../\r\n"
            b"Content-Length: 0\r\n\r\n"
        )

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!"
        )


class Http404Protocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)
        transport.write(
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 19\r\n\r\n"
            b"HTTP 404: Not Found"
        )


class ConnectionClosedProtocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)

        transport.write(b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello,")
        transport.close()


class UrandomProtocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)

        transport.write(os.urandom(128 * 1024))


class MalformedProtocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)
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
        "user-agent": helpers.get_version_str(),
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
        "user-agent": helpers.get_version_str(),
        "accept": "*/*",
        "host": f"localhost:{mocked_unix_server.port}",
    }

    mocked_unix_server.select_proto().assert_initial(
        b"GET / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Accept: */*",
        f"Host: localhost:{mocked_unix_server.port}".encode(),
    )


@pytest.mark.asyncio
async def test_json(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = JsonResponseProtocol
    async with HttpClient() as client:
        response = await client.get(f"http://localhost:{mocked_server.port}")

        assert response.status_code == 200
        assert response.body.to_json() == {"a": "b"}

        mocked_server.select_proto().assert_initial(
            b"GET / HTTP/1.1",
            b"User-Agent: %(self_ver_bytes)s",
            b"Accept: */*",
            f"Host: localhost:{mocked_server.port}".encode(),
        )


@pytest.mark.asyncio
async def test_path_args(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = GetEchoProtocol

    async with HttpClient() as client:
        response = await client.get(
            f"http://localhost:{mocked_server.port}/?a=b", path_args={"c": "d"}
        )

        assert response.status_code == 200
        assert response.body == b"Hello, World!"

        mocked_server.select_proto().assert_initial(
            b"GET /?a=b&c=d HTTP/1.1",
            b"User-Agent: %(self_ver_bytes)s",
            b"Accept: */*",
            f"Host: localhost:{mocked_server.port}".encode(),
        )


@pytest.mark.asyncio
async def test_default_no_redirect(
    mocked_server: helpers.MockedServer,
) -> None:
    mocked_server.mock_proto_cls = AlwaysRedirectProtocol
    async with HttpClient() as client:
        response = await client.get(f"http://localhost:{mocked_server.port}/")

        assert response.status_code == 302
        assert response.headers["location"] == "/"


@pytest.mark.asyncio
async def test_redirect_successful(
    mocked_server: helpers.MockedServer,
) -> None:
    mocked_server.mock_proto_cls = Redirect10TimesProtocol
    async with HttpClient() as client:
        response = await client.get(
            f"http://localhost:{mocked_server.port}/", follow_redirection=True
        )

        assert response.status_code == 200
        assert response.body == b"Hello, World!"


@pytest.mark.asyncio
async def test_too_many_redirects(
    mocked_server: helpers.MockedServer,
) -> None:
    mocked_server.mock_proto_cls = AlwaysRedirectProtocol
    async with HttpClient() as client:
        with pytest.raises(TooManyRedirects):
            await client.get(
                f"http://localhost:{mocked_server.port}/",
                follow_redirection=True,
            )


@pytest.mark.asyncio
async def test_prevent_relative_redirect(
    mocked_server: helpers.MockedServer,
) -> None:
    mocked_server.mock_proto_cls = RelativeRedirectProtocol
    async with HttpClient() as client:
        with pytest.raises(FailedRedirection):
            await client.get(
                f"http://localhost:{mocked_server.port}/",
                follow_redirection=True,
            )


@pytest.mark.asyncio
async def test_response_404(
    mocked_server: helpers.MockedServer,
) -> None:
    mocked_server.mock_proto_cls = Http404Protocol
    async with HttpClient() as client:
        with pytest.raises(HttpError) as exc_info:
            await client.get(f"http://localhost:{mocked_server.port}/")

        assert exc_info.value.status_code == 404
        assert exc_info.value.status_description == "Not Found"


@pytest.mark.asyncio
async def test_response_404_no_raise(
    mocked_server: helpers.MockedServer,
) -> None:
    mocked_server.mock_proto_cls = Http404Protocol
    async with HttpClient(raise_error=False) as client:
        response = await client.get(f"http://localhost:{mocked_server.port}/")

        assert response.status_code == 404
        assert response.body == b"HTTP 404: Not Found"


@pytest.mark.asyncio
async def test_connection_closed(
    mocked_server: helpers.MockedServer,
) -> None:
    mocked_server.mock_proto_cls = ConnectionClosedProtocol
    async with HttpClient() as client:
        with pytest.raises(ConnectionClosed):
            await client.get(f"http://localhost:{mocked_server.port}/")


@pytest.mark.asyncio
async def test_too_large(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = GetEchoProtocol
    async with HttpClient(max_body_size=12) as client:
        with pytest.raises(ResponseEntityTooLarge):
            await client.get(f"http://localhost:{mocked_server.port}/")


@pytest.mark.asyncio
async def test_too_large_2(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = UrandomProtocol
    async with HttpClient(max_body_size=12) as client:
        with pytest.raises(ResponseEntityTooLarge):
            await client.get(f"http://localhost:{mocked_server.port}/")


@pytest.mark.asyncio
async def test_malformed_data(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = MalformedProtocol
    async with HttpClient(max_body_size=12) as client:
        with pytest.raises(BadResponse):
            await client.get(f"http://localhost:{mocked_server.port}/")
