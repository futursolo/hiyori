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

import asyncio
import hiyori
import magichttp


class MockServer(asyncio.Protocol):
    def __init__(self):
        self.transport = None
        self.data_chunks = []
        self.eof = False
        self.exc = None
        self.conn_lost = False

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data):
        self.data_chunks.append(data)

    def eof_received(self):
        self.eof = True
        return True

    def connection_lost(self, exc):
        self.exc = exc
        self.conn_lost = True


class TestHelper:
    def __init__(self):
        self.loop = asyncio.get_event_loop()

        self.loop.set_debug(True)

        self._tsks = set()

        self.mock_srv = None

    def run_async_test(self, coro_fn):
        async def test_coro(_self, *args, **kwargs):
            exc = None

            try:
                await asyncio.wait_for(
                    coro_fn(_self, *args, **kwargs), timeout=5)

            except Exception as e:
                exc = e

            self._tsks, tsks = set(), self._tsks

            for tsk in tsks:

                try:
                    if not tsk.done():
                        tsk.cancel()

                    await tsk

                except asyncio.CancelledError:
                    continue

                except Exception as e:
                    if not exc:
                        exc = e

            if exc:
                raise RuntimeError from exc

        def wrapper(_self, *args, **kwargs):
            self.loop.run_until_complete(test_coro(_self, *args, **kwargs))

        return wrapper

    def create_task(self, coro):
        tsk = self.loop.create_task(coro)

        self._tsks.add(tsk)

        return tsk

    def with_server(self, srv_cls):
        class _Server(srv_cls):
            def connection_made(_self, transport):
                super().connection_made(transport)
                self.mock_srv = _self

            def connection_lost(_self, exc):
                super().connection_lost(exc)

        def decorator(fn):
            async def wrapper(_self, *args, **kwargs):
                srv = await self.loop.create_server(
                    _Server, host="localhost", port=8000)

                try:
                    result = await fn(_self, *args, **kwargs)

                except Exception:
                    raise

                finally:
                    srv.close()
                    await srv.wait_closed()

                    self.mock_srv = None

                return result

            return wrapper

        return decorator

    def get_version_str(self):
        return f"hiyori/{hiyori.__version__} magichttp/{magichttp.__version__}"

    def get_version_bytes(self):
        return self.get_version_str().encode()

    def assert_initial_bytes(self, buf, first_line, *header_lines):
        buf_initial = buf.split(b"\r\n\r\n")[0]
        buf_parts = buf_initial.split(b"\r\n")

        assert buf_parts.pop(0) == first_line

        assert len(buf_parts) == len(set(buf_parts))
        assert len(buf_parts) == len(header_lines)

        for line in header_lines:
            line = line % {b"self_ver_bytes": self.get_version_bytes()}
            assert line in buf_parts
