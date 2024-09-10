# Use an ARM64 compatible Python base image
FROM python:3.11.4-slim

EXPOSE 8000

# Set the working directory in the container
WORKDIR /app

# Note: Ensure all packages are available for ARM64 architecture in the base image's repository
RUN apt-get update && apt-get install -y \
    libssl-dev \
    gcc \
    curl \
    libxml2-dev \
    libxslt-dev \
    zlib1g-dev \
    libjpeg62-turbo-dev \
    && rm -rf /var/lib/apt/lists/*
    
RUN pip install --upgrade pip

# Copy the requirements file
COPY requirements.txt ./

RUN pip install -r requirements.txt

# Copy the rest of your application's source code from your host to your image filesystem.
COPY . .

# Run app.py when the container launches
CMD ["python", "app.py"]
