FROM python:3.12-slim
WORKDIR /app
COPY server.py auth.py energy_store.py config.py metrics.py .
COPY static ./static
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 80
CMD ["python", "server.py"]
