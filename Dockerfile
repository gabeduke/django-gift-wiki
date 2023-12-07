# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install pipenv and compile the dependencies in the Pipfile.lock
RUN pip install --upgrade pip && \
    pip install pipenv

# Install dependencies
COPY Pipfile Pipfile.lock ./
RUN pipenv install --deploy --ignore-pipfile

# Copy project
COPY . /app/

# Run the application
CMD ["pipenv", "run", "gunicorn", "--bind", "0.0.0.0:8000", "giftwiki.wsgi:application"]
