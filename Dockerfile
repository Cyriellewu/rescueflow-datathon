# RescueNYC API + dashboard for the LinuxONE (s390x) VM.
# The default base is the LinuxONE Community Cloud ML image, which already ships pandas,
# scikit-learn and xgboost built for s390x (PyPI has no s390x wheels for pandas).
#   docker build -t rescuenyc .
#   docker run -d --name rescuenyc -p 8000:8000 -v $PWD/artifacts:/app/artifacts rescuenyc
ARG BASE=registry.linuxone.cloud.marist.edu/l1cc/jupyterlab-image-s390x
FROM ${BASE}

USER root
RUN pip install --no-cache-dir fastapi uvicorn
WORKDIR /app
COPY rescueflow/ rescueflow/
COPY scripts/ scripts/
COPY app/ app/
COPY spatial/ spatial/
RUN useradd --system --uid 10001 rescuenyc 2>/dev/null || true
USER 10001

ENV RESCUENYC_ARTIFACTS=/app/artifacts
EXPOSE 8000
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "rescueflow.api:app", "--host", "0.0.0.0", "--port", "8000"]
