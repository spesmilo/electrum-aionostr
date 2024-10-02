#!/usr/bin/env python

"""The setup script."""

from setuptools import setup, find_packages

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

requirements = [
    "electrum_ecc",
    "websockets",
    "cryptography>=37.0.4",
]

test_requirements = [
    "pytest>=3",
]

setup(
    author="Dave St.Germain",
    author_email="dave@st.germa.in",
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    description="asyncio nostr client",
    entry_points={
        "console_scripts": [
            "aionostr=aionostr.cli:main",
        ],
    },
    install_requires=requirements,
    license="BSD license",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="aionostr",
    name="electrum-aionostr",
    packages=find_packages(include=["aionostr", "aionostr.*"]),
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/spesmilo/electrum-aionostr",
    version="0.0.1",
    zip_safe=False,
)
