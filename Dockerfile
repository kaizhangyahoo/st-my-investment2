# Use official Playwright Python image
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy the rest of the application
COPY . .

# Expose the port Streamlit will run on
EXPOSE 8080

# Command to run the application
# We use rewrite_login.py as the entry point
CMD ["streamlit", "run", "rewrite_login.py", "--server.port=8080", "--server.address=0.0.0.0"]
