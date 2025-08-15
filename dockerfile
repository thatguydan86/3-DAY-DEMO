# Use official Python base image
FROM python:3.11-slim

# Prevents Python from writing pyc files and forces stdout/stderr to flush
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    git \
    build-essential \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libgtk-3-0 \
    libasound2 \
    libxshmfence1 \
    libx11-xcb1 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Copy dependency list
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and Chromium
RUN pip install playwright && playwright install --with-deps chromium

# Copy project files
COPY . .

# Expose port (optional)
EXPOSE 8080

# Run the scraper
CMD ["python", "main.py"]
