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

from setuptools import setup, find_packages

import sys

if not sys.version_info[:3] >= (3, 6, 1):
    raise RuntimeError("Hiyori requires Python 3.6.1 or higher.")

setup_requires = [
    "setuptools>=50",
    "pytest-runner>=5.2,<6",
    "setuptools-scm>=4.1.2",
]

install_requires = [
    "magichttp>=1.1.1,<2",
    "magicdict>=1.0.6,<2",
    "importlib-metadata>=1.7.0;python_version<'3.8'",
]

tests_require = ["pytest>=6.0.1,<7", "mypy>=0.782,<1", "flake8>=3.8.3,<4"]


if __name__ == "__main__":
    setup(
        name="hiyori",
        use_scm_version={"local_scheme": lambda v: ""},
        author="Kaede Hoshikawa",
        author_email="futursolo@icloud.com",
        url="https://github.com/futursolo/hiyori",
        license="Apache License 2.0",
        description="Hiyori is an http client for asyncio.",
        long_description=open("README.rst", "r").read(),
        packages=find_packages(),
        package_data={"": ["*"]},
        include_package_data=True,
        setup_requires=setup_requires,
        install_requires=install_requires,
        tests_require=tests_require,
        extras_require={"test": tests_require},
        zip_safe=False,
        classifiers=[
            "Operating System :: MacOS",
            "Operating System :: MacOS :: MacOS X",
            "Operating System :: Microsoft",
            "Operating System :: Microsoft :: Windows",
            "Operating System :: POSIX",
            "Operating System :: POSIX :: Linux",
            "Operating System :: Unix",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3 :: Only",
            "Programming Language :: Python :: Implementation :: CPython",
        ],
    )
