FROM postgres:16
RUN apt-get update -qq && apt-get install -y --no-install-recommends python3 age && rm -rf /var/lib/apt/lists/*
COPY infra/control/tool_database.py /usr/local/bin/app-database.py
