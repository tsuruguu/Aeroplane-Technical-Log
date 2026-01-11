FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

#CMD ["python", "fix_admin.py"]
CMD ["python", "app.py"]

# CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:create_app()"]