FROM python:3.10-slim

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/logs && chown -R appuser:appuser /app/logs

COPY . .
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

#CMD ["python", "fix_admin.py"]
CMD ["python", "app.py"]

# CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:create_app()"]