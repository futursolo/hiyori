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

import helpers
import pytest

from hiyori import HttpClient, HttpRequestMethod, HttpVersion, post


class PostEchoProtocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)
        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!"
        )


@pytest.mark.asyncio
async def test_simple(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = PostEchoProtocol

    response = await post(
        f"http://localhost:{mocked_server.port}", body=b"1234567890"
    )

    assert response.status_code == 200
    assert response.body == b"Hello, World!"
    assert response.version == HttpVersion.V1_1
    assert response.headers == {"content-length": "13"}

    assert response.request.method == HttpRequestMethod.POST
    assert response.request.version == HttpVersion.V1_1
    assert response.request.uri == "/"
    assert response.request.authority == f"localhost:{mocked_server.port}"
    assert not hasattr(response.request, "scheme")
    assert response.request.headers == {
        "user-agent": helpers.get_version_str(),
        "content-length": "10",
        "accept": "*/*",
        "host": f"localhost:{mocked_server.port}",
    }


@pytest.mark.asyncio
async def test_urlencoded_body(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = PostEchoProtocol

    async with HttpClient() as client:
        response = await client.post(
            f"http://localhost:{mocked_server.port}", body={"a": "b", "c": "d"}
        )

    assert response.request.headers == {
        "user-agent": helpers.get_version_str(),
        "content-type": "application/x-www-form-urlencoded",
        "content-length": "7",
        "accept": "*/*",
        "host": f"localhost:{mocked_server.port}",
    }

    proto = mocked_server.select_proto()

    initial_bytes, body = b"".join(proto.data_chunks).split(b"\r\n\r\n", 1)

    proto.assert_initial(
        b"POST / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Content-Type: application/x-www-form-urlencoded",
        b"Content-Length: 7",
        b"Accept: */*",
        f"Host: localhost:{mocked_server.port}".encode(),
    )

    assert body == b"a=b&c=d"


@pytest.mark.asyncio
async def test_json_body(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = PostEchoProtocol

    async with HttpClient() as client:
        response = await client.post(
            f"http://localhost:{mocked_server.port}",
            json={"a": "b", "c": [1, 2]},
        )

    assert response.request.headers == {
        "user-agent": helpers.get_version_str(),
        "content-type": "application/json",
        "content-length": "23",
        "accept": "*/*",
        "host": f"localhost:{mocked_server.port}",
    }

    proto = mocked_server.select_proto()

    initial_bytes, body = b"".join(proto.data_chunks).split(b"\r\n\r\n", 1)

    proto.assert_initial(
        b"POST / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Content-Type: application/json",
        b"Content-Length: 23",
        b"Accept: */*",
        f"Host: localhost:{mocked_server.port}".encode(),
    )

    assert body == b'{"a": "b", "c": [1, 2]}'


@pytest.mark.asyncio
async def test_urlencoded_and_json_body(
    mocked_server: helpers.MockedServer,
) -> None:
    mocked_server.mock_proto_cls = PostEchoProtocol
    async with HttpClient() as client:
        with pytest.raises(ValueError):
            await client.post(
                f"http://localhost:{mocked_server.port}",
                body={"a": "b"},
                json={"c": "d"},
            )
