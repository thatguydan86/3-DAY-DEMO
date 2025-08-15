FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy dependencies file and install
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app files
COPY . .

# Run the bot
CMD ["python", "main.py"]
