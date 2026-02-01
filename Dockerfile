FROM python:3.9-slim

WORKDIR /app

# Najpierw instalujemy biblioteki (to się rzadko zmienia)
RUN pip install --no-cache-dir flask docker werkzeug

# Dopiero potem kopiujemy kod (to zmieniasz często)
COPY . .

EXPOSE 5000

# Optymalizacja: wyłączamy buforowanie logów, żeby widzieć błędy w konsoli od razu
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]