FROM python:3.12-slim

ARG PIP_TOOLS_VERSION=7.4.1
RUN pip install --no-cache-dir "pip-tools==${PIP_TOOLS_VERSION}"

WORKDIR /work
