FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install handy networking tools for debugging inside the container
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        wget \
        iputils-ping \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Install runtime dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Provide a default volume for config/state overrides
VOLUME ["/config", "/data"]

# Default entrypoint runs the monitor with externalised config/state paths
ENTRYPOINT ["python", "main.py", "--config", "/config/config.yaml"]
