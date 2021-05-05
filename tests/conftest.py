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

from typing import Generator
import asyncio
import os

import helpers
import pytest

import hiyori


@pytest.fixture(autouse=True, scope="session")
def update_resolver() -> None:
    desired_resolver = os.environ.get("HIYORI_RESOLVER")

    if desired_resolver is None:
        return

    if desired_resolver == "SYSTEM":
        hiyori.resolvers.DefaultResolver = hiyori.resolvers.SystemResolver

    elif desired_resolver == "ASYNC":  # noqa: SIM106
        hiyori.resolvers.DefaultResolver = hiyori.resolvers.AsyncResolver

    else:
        raise ValueError(f"{desired_resolver} is not a valid resolver.")


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    # Not replacing the event loop for now, but will do this in the future
    # When servers are tied to event loops
    loop = asyncio.get_event_loop()

    if loop.is_closed():
        loop = asyncio.new_event_loop()

    yield loop


@pytest.fixture
def mocked_server(
    event_loop: asyncio.AbstractEventLoop,
) -> Generator[helpers.MockedServer, None, None]:
    async def create_mocked_server() -> helpers.MockedServer:
        srv = helpers.MockedServer()
        return await srv.__aenter__()

    async def close_mocked_server(srv: helpers.MockedServer) -> None:
        await srv.__aexit__()

    srv = event_loop.run_until_complete(create_mocked_server())

    yield srv

    event_loop.run_until_complete(close_mocked_server(srv))
