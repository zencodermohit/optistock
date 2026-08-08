# ==== BUILD STAGE ====
FROM python:3.12-slim as builder

WORKDIR /app

# Install system dependencies needed for compiling python packages (like psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ==== RUNTIME STAGE ====
FROM python:3.12-slim

WORKDIR /app

# Install only the runtime dependencies for PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy the application code
COPY . .

# Copy entrypoint script and make it executable
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Expose the API port
EXPOSE 8000

# The entrypoint migrates (when asked to) and then execs whatever it is given.
# CMD supplies that default, so `docker compose up` still runs the API -- while
# the relay and consumer services can override it with their own command and
# actually be run. Before CMD existed the entrypoint hard-coded uvicorn, and
# every service in the stack silently became a copy of the web server.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
