# Image used by the gatekeeper when settings.sandbox is 'docker'.
# Build once:  python -m farm sandbox-build
# Tests run with no network, so everything the tasks need must be installed here.
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest
WORKDIR /work
