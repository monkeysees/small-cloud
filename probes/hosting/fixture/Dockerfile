FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254
RUN apt-get update -qq && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
WORKDIR /probe
COPY network.py targets.json ./
RUN python3 network.py check --config targets.json --phase build
ENV PORT=8080
USER 65532:65532
CMD ["python3", "/probe/network.py", "serve"]
