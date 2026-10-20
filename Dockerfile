# Production image for a PyFusion web app
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYFUSION_ENV=production

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt pyproject.toml README.md LICENSE ./
COPY fusionlib ./fusionlib
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir .

# Copy the application
COPY . .

# Run as an unprivileged user
RUN useradd --create-home --uid 10001 pyfusion && chown -R pyfusion /app
USER pyfusion

EXPOSE 5000

# PYFUSION_SECRET_KEY must be provided at runtime: docker run -e PYFUSION_SECRET_KEY=... (the server refuses to start without it)
CMD ["pyfusion", "run", "web", "--production", "--host", "0.0.0.0", "--port", "5000"]
