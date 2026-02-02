FROM python:3.11-slim

# Instalacja zależności systemowych (czasem potrzebne dla PyYAML)
RUN apt-get update && apt-get install -y gcc python3-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalujemy biblioteki bezpośrednio, żeby nie było wątpliwości
RUN pip install --no-cache-dir flask docker PyYAML psutil werkzeug

COPY . .

CMD ["python", "app.py"]
