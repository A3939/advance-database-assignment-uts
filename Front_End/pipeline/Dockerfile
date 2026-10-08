FROM python:3.12.6-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/pipeline
COPY requirements.txt requirements-intake.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd -g 10001 arsia && useradd -u 10001 -g arsia arsia \
    && mkdir -p /app/artifacts/imports-local /run/arsia \
    && chown -R arsia:arsia /app/artifacts /run/arsia
COPY arsia_pipeline ./arsia_pipeline
COPY AUTONOMOUS_CONTRACT.md ./AUTONOMOUS_CONTRACT.md
USER 10001:10001
ENTRYPOINT ["python", "-m", "arsia_pipeline.cli"]
