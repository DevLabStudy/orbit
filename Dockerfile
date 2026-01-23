FROM python:3.9-slim

# Instalacja zależności
RUN pip install --no-cache-dir flask docker werkzeug

WORKDIR /app
COPY . .

# Port aplikacji
EXPOSE 5000

CMD ["python", "app.py"]