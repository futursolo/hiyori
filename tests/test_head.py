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

from hiyori import HttpRequestMethod, HttpVersion, head


class HeadEchoProtocol(helpers.BaseMockProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        super().connection_made(transport)

        assert isinstance(transport, asyncio.Transport)
        transport.write(b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\n")


@pytest.mark.asyncio
async def test_simple(mocked_server: helpers.MockedServer) -> None:
    mocked_server.mock_proto_cls = HeadEchoProtocol

    response = await head(f"http://localhost:{mocked_server.port}")

    assert response.status_code == 200
    assert response.body == b""
    assert response.version == HttpVersion.V1_1
    assert response.headers == {"content-length": "13"}

    assert response.request.method == HttpRequestMethod.HEAD
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
        b"HEAD / HTTP/1.1",
        b"User-Agent: %(self_ver_bytes)s",
        b"Accept: */*",
        f"Host: localhost:{mocked_server.port}".encode(),
    )
