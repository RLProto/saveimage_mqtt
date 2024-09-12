# Use an ARM64 compatible Python base image
FROM python:3.11.4-slim

EXPOSE 8000

# Set the working directory in the container
WORKDIR /app

# Install necessary packages including PostgreSQL dev libraries, C++ compiler, and CMake for building packages
RUN apt-get update && apt-get install -y \
    libssl-dev \
    gcc \
    g++ \
    curl \
    cmake \
    ninja-build \
    libxml2-dev \
    libxslt-dev \
    zlib1g-dev \
    libjpeg62-turbo-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

# Copy the requirements file
COPY requirements.txt ./

# Install Python dependencies
RUN pip install -r requirements.txt

# Copy the rest of your application's source code from your host to your image filesystem
COPY . .

# Run app.py when the container launches
CMD ["python", "main.py"]
