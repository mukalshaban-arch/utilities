# Lightweight Python image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy and load  requirements.txt first To keep changes updated
COPY requirements.txt .

#Command to install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Command to run the Flask application - bound to 0.0.0.0 to be accessible outside the container
#CMD [ "flask", "run", "--host", "0.0.0.0" ]

#To run the application
CMD ["python", "app.py"]
