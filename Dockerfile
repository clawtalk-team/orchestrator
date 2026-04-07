FROM python:3.11-slim

ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT}

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Expose port
EXPOSE 8571

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8571"]
