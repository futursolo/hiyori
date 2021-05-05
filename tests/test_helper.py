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

import magichttp

import hiyori


class _SkeletonServer(asyncio.Protocol):
    def connection_made(self, transport):
        print("Connection made.")

        if helper.mock_srv_cls is None:
            transport.close()

            return

        self._mock_srv = helper.mock_srv_cls()

        self._mock_srv.connection_made(transport)

    def data_received(self, data):
        print(f"Data received: {data!r}.")
        helper.mock_srv = self._mock_srv

        self._mock_srv.data_received(data)

    def eof_received(self):
        print("Eof received.")

        return self._mock_srv.eof_received()

    def connection_lost(self, exc):
        print("Connection lost.")
        if exc:
            print(exc)

        self._mock_srv.connection_lost(exc)


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


class _TestHelper:
    def __init__(self):
        self.loop = asyncio.get_event_loop()

        self.loop.set_debug(True)

        self._tsks = set()

        self.mock_srv = None
        self.mock_srv_cls = None

        self._srv = self.loop.run_until_complete(
            self.loop.create_server(
                _SkeletonServer, host="localhost", port=8000
            )
        )

    def run_async_test(self, *args, with_srv_cls=None):
        def decorator(coro_fn):
            async def test_coro(_self, *args, **kwargs):
                self.mock_srv_cls = with_srv_cls

                exc = None

                try:
                    await asyncio.wait_for(
                        coro_fn(_self, *args, **kwargs), timeout=5
                    )

                except Exception as e:
                    exc = e

                if self.mock_srv:
                    self.mock_srv.transport.close()
                    self.mock_srv = None

                self._tsks, tsks = set(), self._tsks

                for tsk in tsks:
                    try:
                        if not tsk.done():
                            tsk.cancel()

                        await tsk

                    except asyncio.CancelledError:
                        continue

                    except BaseException as e:
                        if not exc:
                            exc = e

                if exc:
                    raise exc

            def wrapper(_self, *args, **kwargs):
                self.loop.run_until_complete(test_coro(_self, *args, **kwargs))

            return wrapper

        if args:
            if len(args) > 1:
                raise RuntimeError("Only one positional argument is allowed.")

            if with_srv_cls is not None:
                raise RuntimeError("This is not okay.")

            return decorator(args[0])

        if with_srv_cls is None:
            raise RuntimeError("You must provide a server class.")

        return decorator

    def create_task(self, coro):
        tsk = self.loop.create_task(coro)

        self._tsks.add(tsk)

        return tsk

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
            line = line % {  # noqa: S001
                b"self_ver_bytes": self.get_version_bytes()
            }
            assert line in buf_parts

    def __del__(self):
        self._srv.close()
        self.loop.run_until_complete(self._srv.wait_closed())


helper = _TestHelper()
