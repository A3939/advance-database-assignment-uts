FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
RUN pip install --no-cache-dir pandas==2.2.3 numpy==2.2.6 matplotlib==3.10.3
COPY runner.py /opt/arsia/runner.py
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg MPLCONFIGDIR=/analysis/.mpl TMPDIR=/analysis
USER 65534:65534
WORKDIR /analysis
ENTRYPOINT ["python", "-I", "/opt/arsia/runner.py"]
