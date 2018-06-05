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

from typing import Any

import typing

if typing.TYPE_CHECKING:
    from . import messages  # noqa: F401
    from . import constants  # noqa: F401

__all__ = [
    "BaseHiyoriException",
    "RequestTimeout",
    "BadResponse",
    "ResponseEntityTooLarge",
    "HttpError",
    "FailedRedirection",
    "TooManyRedirects"]


class BaseHiyoriException(Exception):
    """
    The base class of all hiyori exceptions.
    """
    pass


class RequestTimeout(BaseHiyoriException, TimeoutError):
    """
    Raised when the server has not responded before timeout.
    """
    pass


class BadResponse(BaseHiyoriException):
    """
    Raised when a bad response is received.
    """
    pass


class ResponseEntityTooLarge(BaseHiyoriException):
    """
    Raised when hiyori received an entity larger than
    :code:`max_initial_size` or :code:`max_body_size`.
    """
    pass


class HttpError(BaseHiyoriException):
    def __init__(self, __response: "messages.Response", *args: Any) -> None:
        self._response = __response

        super().__init__(
            "HTTP {} {}: ".format(
                int(self.status_code), self.status_code.phrase),
            *args, str(self._response))

    @property
    def response(self) -> "messages.Response":
        return self._response

    @property
    def status_code(self) -> "constants.HttpStatusCode":
        return self.response.status_code

    @property
    def status_description(self) -> str:
        return self.response.status_code.phrase  # type: ignore


class FailedRedirection(BaseHiyoriException):
    """
    Raised with hiyori cannot fulfill the redirection request.
    """
    pass


class TooManyRedirects(FailedRedirection):
    """
    Raise when the number of redirects exceeds :code:`max_redirect_num`.
    """
    def __init__(self, last_request: "messages.Request", *args: Any) -> None:
        self._last_request = last_request

        super().__init__(*args, (str(self._last_request)))

    @property
    def last_request(self) -> "messages.Request":
        return self._last_request


class ConnectionClosed(BaseHiyoriException):
    """
    Raised when the connection is being closed unexpectedly.
    """
    pass
