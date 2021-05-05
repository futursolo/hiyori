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
import ipaddress
import pathlib

import pytest

from hiyori.resolvers import HostsResolver
import hiyori

_TEST_HOST_PATH = pathlib.Path(__file__).parent / "files" / "hosts"


@pytest.mark.asyncio
async def test_simple() -> None:
    resolv = HostsResolver(host_path=_TEST_HOST_PATH)

    result = await resolv.lookup("localhost", 9999)

    assert result.host == "localhost"
    assert result.port == 9999
    assert result.results == set(
        [
            (ipaddress.ip_address("127.0.0.1"), 9999),
            (ipaddress.ip_address("::1"), 9999),
        ]
    )


@pytest.mark.asyncio
async def test_cache() -> None:
    resolv = HostsResolver(host_path=_TEST_HOST_PATH, min_ttl=1)

    result = await resolv.lookup("localhost", 9999)

    assert result.host == "localhost"
    assert result.port == 9999
    assert result.results == set(
        [
            (ipaddress.ip_address("127.0.0.1"), 9999),
            (ipaddress.ip_address("::1"), 9999),
        ]
    )

    result2 = await resolv.lookup("localhost", 9999)
    assert result is result2

    await asyncio.sleep(1)
    result3 = await resolv.lookup("localhost", 9999)

    assert result3 is not result


@pytest.mark.asyncio
async def test_override() -> None:
    resolv = HostsResolver(host_path=_TEST_HOST_PATH)

    with pytest.raises(hiyori.UnresolvableHost):
        await resolv.lookup("something.that-is.unresolvable", 9999)

    resolv.override(
        "something.that-is.unresolvable",
        9999,
        (ipaddress.ip_address("1.2.3.4"), 8888),
    )

    result = await resolv.lookup("something.that-is.unresolvable", 9999)

    assert result.host == "something.that-is.unresolvable"
    assert result.port == 9999
    assert result.results == set(
        [
            (ipaddress.ip_address("1.2.3.4"), 8888),
        ]
    )

    result = await resolv.lookup("localhost", 9999)

    assert result.host == "localhost"
    assert result.port == 9999
    assert result.results == set(
        [
            (ipaddress.ip_address("127.0.0.1"), 9999),
            (ipaddress.ip_address("::1"), 9999),
        ]
    )

    resolv.override(
        "localhost",
        9999,
        (ipaddress.ip_address("::2"), 7777),
    )

    result = await resolv.lookup("localhost", 9999)

    assert result.host == "localhost"
    assert result.port == 9999
    assert result.results == set(
        [
            (ipaddress.ip_address("::2"), 7777),
        ]
    )

    resolv.remove_override("localhost", 9999)

    result = await resolv.lookup("localhost", 9999)

    assert result.host == "localhost"
    assert result.port == 9999
    assert result.results == set(
        [
            (ipaddress.ip_address("127.0.0.1"), 9999),
            (ipaddress.ip_address("::1"), 9999),
        ]
    )

    resolv.remove_override("something.that-is.unresolvable", 9999)

    with pytest.raises(hiyori.UnresolvableHost):
        await resolv.lookup("something.that-is.unresolvable", 9999)


@pytest.mark.asyncio
async def test_not_exist() -> None:
    resolv = HostsResolver(host_path=_TEST_HOST_PATH)

    with pytest.raises(hiyori.UnresolvableHost):
        await resolv.lookup("something.that-does.not-exist", 9999)


@pytest.mark.asyncio
async def test_system() -> None:
    # This tests that HostsResolver can correctly find system hosts file
    # This requires the system where the test is run has a hosts file
    # with localhost pointed to 127.0.0.1

    resolv = HostsResolver()

    result = await resolv.lookup("localhost", 9999)

    assert result.host == "localhost"
    assert result.port == 9999
    assert (ipaddress.ip_address("127.0.0.1"), 9999) in result.results
