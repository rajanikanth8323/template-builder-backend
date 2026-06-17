# FROM python:3.11-slim

# WORKDIR /app

# # Install Python dependencies
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# # Verify key packages installed correctly
# RUN python -c "import reportlab; print('reportlab OK:', reportlab.Version)"
# RUN python -c "import docx; print('python-docx OK')"

# # Copy application source
# COPY backend/src /app/src

# # Ensure __init__.py files exist
# RUN touch /app/src/__init__.py && \
#     touch /app/src/api/__init__.py && \
#     touch /app/src/core/__init__.py && \
#     mkdir -p /app/src/core/renderers && \
#     touch /app/src/core/renderers/__init__.py

# # Environment variables
# ENV APP_ENV=prod
# ENV DB_URL=${DB_URL}
# ENV PYTHONPATH=/app/src

# EXPOSE 8080

# CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]

FROM python:3.11-slim

WORKDIR /app

# Install FreeSans fonts for Hindi/Indian script support in PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY backend/src /app/src

# Ensure __init__.py files exist
RUN touch /app/src/__init__.py && \
    touch /app/src/api/__init__.py && \
    touch /app/src/core/__init__.py && \
    mkdir -p /app/src/core/renderers && \
    touch /app/src/core/renderers/__init__.py

# Environment variables
ENV APP_ENV=prod
ENV DB_URL=${DB_URL}
ENV PYTHONPATH=/app/src

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]