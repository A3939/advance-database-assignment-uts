FROM python:3.12.6-slim-bookworm@sha256:ad48727987b259854d52241fac3bc633574364867b8e20aec305e6e7f4028b26 AS verified
ARG ARSIA_REVISION
WORKDIR /verified/project
COPY . .
RUN python tools/check_inventory.py
RUN python docker/team/provenance.py --root . --proof artifacts/team/build-provenance.objects \
    --revision "$ARSIA_REVISION" --output /verified/git-provenance.json \
    && rm artifacts/team/build-provenance.objects && rmdir artifacts/team artifacts

FROM python:3.12.6-slim-bookworm@sha256:ad48727987b259854d52241fac3bc633574364867b8e20aec305e6e7f4028b26 AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /build
COPY --from=verified /verified/project /build
RUN python -m pip download --require-hashes --only-binary=:all: -r docker/team/requirements.lock -d /wheels \
    && python -m pip install --no-index --find-links=/wheels --require-hashes -r docker/team/requirements.lock
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir=/wheels .

FROM python:3.12.6-slim-bookworm@sha256:ad48727987b259854d52241fac3bc633574364867b8e20aec305e6e7f4028b26
ARG ARSIA_REVISION=working-tree
LABEL org.opencontainers.image.source="https://github.com/A3939/advance-database-assignment-uts" \
      org.opencontainers.image.revision=$ARSIA_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ARSIA_IMAGE_REVISION=$ARSIA_REVISION TZ=UTC
COPY --from=build /wheels /opt/arsia/wheels
COPY --from=verified /verified/project /opt/arsia/project
COPY --from=verified /verified/git-provenance.json /opt/arsia/git-provenance.json
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
