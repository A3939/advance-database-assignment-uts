FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
COPY requirements-intake.txt /tmp/requirements-intake.txt
RUN pip install --no-cache-dir --timeout 120 --retries 3 -r /tmp/requirements-intake.txt openpyxl==3.1.5 pyproj==3.7.2
COPY arsia_pipeline/canonical.py arsia_pipeline/timezone_rules.py arsia_pipeline/transform_plan.py arsia_pipeline/adapter_sdk.py arsia_pipeline/intakereaders.py arsia_pipeline/workbook_plan.py arsia_pipeline/table_plan.py arsia_pipeline/lookup_plan.py arsia_pipeline/lookup_projection.py arsia_pipeline/errors.py /opt/arsia/arsia_pipeline/
COPY arsia_pipeline/date_bounds.py arsia_pipeline/metadata_extractors.py arsia_pipeline/parser_guard.py arsia_pipeline/row_preprocessing.py /opt/arsia/arsia_pipeline/
COPY arsia_pipeline/knowledge/date-range.json /opt/arsia/arsia_pipeline/knowledge/date-range.json
COPY arsia_pipeline/knowledge/timezones /opt/arsia/arsia_pipeline/knowledge/timezones
RUN touch /opt/arsia/arsia_pipeline/__init__.py
COPY sandbox/runner.py /opt/arsia/runner.py
# Source checkouts may be private (0600); the unprivileged executor still
# needs read/traverse access to its immutable image libraries, never writes.
RUN chmod -R a+rX /opt/arsia
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 TMPDIR=/tmp PROJ_NETWORK=OFF
USER 65534:65534
WORKDIR /output
ENTRYPOINT ["python","-I","/opt/arsia/runner.py"]
