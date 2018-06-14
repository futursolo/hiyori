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

from hiyori import HttpClient, HttpRequestMethod, HttpVersion, \
     TooManyRedirects, FailedRedirection, HttpError

from test_helper import TestHelper, MockServer

import pytest

helper = TestHelper()


class GetEchoServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!")


class JsonResponseServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n{\"a\": \"b\"}")


class AlwaysRedirectServer(MockServer):
    def data_received(self, data):
        super().data_received(data)

        self.transport.write(
            b"HTTP/1.1 302 Found\r\nLocation: /\r\n"
            b"Content-Length: 0\r\n\r\n")


class Redirect10TimesServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        for _ in range(0, 10):
            transport.write(
                b"HTTP/1.1 302 Found\r\nLocation: /\r\n"
                b"Content-Length: 0\r\n\r\n")

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!")


class RelativeRedirectServer(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 302 Found\r\nLocation: ../\r\n"
            b"Content-Length: 0\r\n\r\n")

        transport.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n\r\nHello, World!")


class Http404Server(MockServer):
    def connection_made(self, transport):
        super().connection_made(transport)

        transport.write(
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 19\r\n\r\n"
            b"HTTP 404: Not Found")


class GetTestCase:
    @helper.run_async_test
    @helper.with_server(GetEchoServer)
    async def test_simple(self):
        async with HttpClient() as client:
            response = await client.get("http://localhost:8000")

            assert response.status_code == 200
            assert response.body == b"Hello, World!"
            assert response.version == HttpVersion.V1_1
            assert response.headers == {"content-length": "13"}

            assert response.request.method == HttpRequestMethod.GET
            assert response.request.version == HttpVersion.V1_1
            assert response.request.uri == "/"
            assert response.request.authority == "localhost:8000"
            assert not hasattr(response.request, "scheme")
            assert response.request.headers == \
                {
                    "user-agent": helper.get_version_str(),
                    "accept": "*/*",
                    "host": "localhost:8000"
                }

            helper.assert_initial_bytes(
                b"".join(helper.mock_srv.data_chunks),
                b"GET / HTTP/1.1",
                b"User-Agent: %(self_ver_bytes)s",
                b"Accept: */*",
                b"Host: localhost:8000")

    @helper.run_async_test
    @helper.with_server(JsonResponseServer)
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
                b"Host: localhost:8000")

    @helper.run_async_test
    @helper.with_server(GetEchoServer)
    async def test_path_args(self):
        async with HttpClient() as client:
            response = await client.get(
                "http://localhost:8000/?a=b", path_args={"c": "d"})

            assert response.status_code == 200
            assert response.body == b"Hello, World!"

            helper.assert_initial_bytes(
                b"".join(helper.mock_srv.data_chunks),
                b"GET /?a=b&c=d HTTP/1.1",
                b"User-Agent: %(self_ver_bytes)s",
                b"Accept: */*",
                b"Host: localhost:8000")

    @helper.run_async_test
    @helper.with_server(AlwaysRedirectServer)
    async def test_default_no_redirect(self):
        async with HttpClient() as client:
            response = await client.get("http://localhost:8000/")

            assert response.status_code == 302
            assert response.headers["location"] == "/"

    @helper.run_async_test
    @helper.with_server(Redirect10TimesServer)
    async def test_redirect_successful(self):
        async with HttpClient() as client:
            response = await client.get(
                "http://localhost:8000/", follow_redirection=True)

            assert response.status_code == 200
            assert response.body == b"Hello, World!"

    @helper.run_async_test
    @helper.with_server(AlwaysRedirectServer)
    async def test_too_many_redirects(self):
        async with HttpClient() as client:
            with pytest.raises(TooManyRedirects):
                await client.get(
                    "http://localhost:8000/", follow_redirection=True)

    @helper.run_async_test
    @helper.with_server(RelativeRedirectServer)
    async def test_prevent_relative_redirect(self):
        async with HttpClient() as client:
            with pytest.raises(FailedRedirection):
                await client.get(
                    "http://localhost:8000/", follow_redirection=True)

    @helper.run_async_test
    @helper.with_server(Http404Server)
    async def test_response_404(self):
        async with HttpClient() as client:
            with pytest.raises(HttpError) as exc_info:
                await client.get("http://localhost:8000/")

            assert exc_info.value.status_code == 404
            assert exc_info.value.status_description == "Not Found"

    @helper.run_async_test
    @helper.with_server(Http404Server)
    async def test_response_404_no_raise(self):
        async with HttpClient(raise_error=False) as client:
            response = await client.get("http://localhost:8000/")

            assert response.status_code == 404
            assert response.body == b"HTTP 404: Not Found"
