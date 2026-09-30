FROM python:3.12-slim

# Security: run as a non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app

# Install dependencies before copying source so Docker can cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Drop to non-root
USER appuser

EXPOSE 8000

# --workers 2 is sufficient — this service is extremely low-traffic
# (only called by Caddy during ACME cert provisioning, not on every request)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
