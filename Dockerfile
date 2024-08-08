# Use the official Python 3.9 slim image as the base image
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all the files from the host to the container's working directory
COPY . .

# Update package lists and install cron
RUN apt-get update && apt-get install -y cron

# Copy the cron job file into the container
COPY my_cron_job /etc/cron.d/my_cron_job

# Set permissions for the cron job file and install the cron job
RUN chmod 0644 /etc/cron.d/my_cron_job
RUN crontab /etc/cron.d/my_cron_job

# Run cron in the foreground
CMD ["cron", "-f"]
