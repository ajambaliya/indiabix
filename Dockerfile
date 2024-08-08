# Use the Python 3.9 slim image as the base image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install the required Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Install cron in the container
RUN apt-get update && apt-get install -y cron

# Copy the cron job definition into the container
COPY my_cron_job /etc/cron.d/my_cron_job

# Set the appropriate permissions for the cron job file
RUN chmod 0644 /etc/cron.d/my_cron_job

# Apply the cron job
RUN crontab /etc/cron.d/my_cron_job

# Start cron and run the Python script
CMD ["cron", "-f"]
