FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config_manager ./config_manager
COPY inventory ./inventory

ENV INVENTORY_PATH=/app/inventory/devices.yaml

EXPOSE 8000
CMD ["uvicorn", "config_manager.api:app", "--host", "0.0.0.0", "--port", "8000"]
