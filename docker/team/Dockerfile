FROM python:3.12.6-slim-bookworm@sha256:ad48727987b259854d52241fac3bc633574364867b8e20aec305e6e7f4028b26 AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY docker/team/requirements.lock /build/docker/team/requirements.lock
RUN python -m pip download --require-hashes --only-binary=:all: -r docker/team/requirements.lock -d /wheels \
    && python -m pip install --no-index --find-links=/wheels --require-hashes -r docker/team/requirements.lock
COPY . /build
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir=/wheels .

FROM python:3.12.6-slim-bookworm@sha256:ad48727987b259854d52241fac3bc633574364867b8e20aec305e6e7f4028b26
ARG ARSIA_REVISION=working-tree
LABEL org.opencontainers.image.source="https://github.com/A3939/advance-database-assignment-uts" \
      org.opencontainers.image.revision=$ARSIA_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ARSIA_IMAGE_REVISION=$ARSIA_REVISION TZ=UTC
COPY --from=build /wheels /opt/arsia/wheels
COPY . /opt/arsia/project
RUN python -m pip install --no-index --find-links=/opt/arsia/wheels --require-hashes -r /opt/arsia/project/docker/team/requirements.lock \
    && python -m pip install --no-index --no-deps /opt/arsia/wheels/arsia_native_intake-0.1.0-py3-none-any.whl \
    && python -m pip check \
    && python /opt/arsia/project/docker/team/image_inputs.py \
    && groupadd -g 10001 arsia && useradd -u 10001 -g arsia -m arsia \
    && mkdir -p /work /data /evidence && chown -R arsia:arsia /work /data /evidence
WORKDIR /work
USER arsia
ENTRYPOINT ["python", "/opt/arsia/project/docker/team/cli.py"]
CMD ["info"]
