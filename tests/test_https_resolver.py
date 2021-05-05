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

import ipaddress

import pytest

from hiyori.resolvers import HttpsResolver
import hiyori


@pytest.mark.asyncio
async def test_simple() -> None:
    resolv = HttpsResolver()

    result = await resolv.lookup("one.one.one.one", 9999)

    assert result.host == "one.one.one.one"
    assert result.port == 9999
    assert result.results == set(
        [
            (ipaddress.ip_address("1.0.0.1"), 9999),
            (ipaddress.ip_address("1.1.1.1"), 9999),
            (ipaddress.ip_address("2606:4700:4700::1111"), 9999),
            (ipaddress.ip_address("2606:4700:4700::1001"), 9999),
        ]
    )

    assert result.ttl >= resolv._min_ttl


@pytest.mark.asyncio
async def test_not_exist() -> None:
    resolv = HttpsResolver()

    with pytest.raises(hiyori.UnresolvableHost):
        await resolv.lookup("something.that-does.not-exist", 9999)
