# Dockerized IG News Download for RPI4

This project provides a Dockerized solution for running the IG news download script on a Raspberry Pi 4 (ARM64).

## Prerequisites
- Docker and Docker Compose installed on your RPI4.
- An IG account (username and password).

## Docker Files

- [Dockerfile.news](Dockerfile.news): Uses the official Playwright Python image (ARM64 compatible).
- [docker-compose.news.yml](docker-compose.news.yml): Simplifies configuration and persistence.
- [.dockerignore](../.dockerignore): Ensures a clean build context.

## How to Run

### Method 1: Docker Compose (Recommended)

1.  **Set your credentials**:
    You can export them in your shell or create a `.env` file in the `ig/` directory:
    ```bash
    export IG_PASSWORD='your_password'
    ```

2.  **Build and Run**:
    ```bash
    # Run from the project root
    docker compose -f ig/docker-compose.news.yml up --build
    ```

3.  **Check Output**:
    The results (CSV and Markdown files) will be saved to the `./ig/news_output` directory on your host machine.

### Method 2: Docker CLI

1.  **Build the image**:
    ```bash
    # Run from the project root
    docker build -t ig-news-scraper -f ig/Dockerfile.news .
    ```

2.  **Run the container**:
    ```bash
    docker run --rm -it \
      -e IG_PASSWORD='your_password' \
      -v $(pwd)/ig/news_output:/app/news_output \
      ig-news-scraper --headless --password 'your_password' --output /app/news_output
    ```

## Notes for RPI4
> [!IMPORTANT]
> The image `mcr.microsoft.com/playwright/python:v1.49.0-noble` supports multiple architectures including `linux/arm64`. Docker will automatically pull the correct version for your RPI4.

> [!TIP]
> Running Playwright in a container on RPI4 can be resource-intensive. Ensure your RPI4 has adequate cooling and power.
