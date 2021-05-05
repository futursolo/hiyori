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

from typing import Type

from .base import BaseResolver, ResolvedResult
from .hosts import HostsResolver
from .https import HttpsResolver
from .system import SystemResolver

__all__ = [
    "ResolvedResult",
    "BaseResolver",
    "SystemResolver",
    "HostsResolver",
    "DefaultResolver",
    "HttpsResolver",
]

try:  # pragma: no cover
    from .async_ import AsyncResolver

    DefaultResolver: Type[BaseResolver] = AsyncResolver
    __all__.append("AsyncResolver")

except ImportError:  # pragma: no cover
    DefaultResolver = SystemResolver
