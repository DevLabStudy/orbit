# Orbit Control

Lekki panel webowy do zarządzania lokalnym Docker Engine — prostsza alternatywa dla Portainera. Orbit pozwala przeglądać i obsługiwać kontenery, obrazy, porty, volume, sieci oraz stacki Docker Compose. Udostępnia również wersjonowane API dla aplikacji desktopowych i mobilnych.

## Funkcje

- kontenery: lista, status, porty, start, stop, restart, usuwanie i logi,
- tworzenie kontenerów z obrazem, nazwą, portami, zmiennymi środowiskowymi i polityką restartu,
- obrazy: pobieranie, budowanie z Dockerfile, szczegóły, usuwanie i czyszczenie obrazów bez tagów,
- volume oraz sieci: tworzenie i usuwanie,
- stacki Docker Compose: tworzenie, lista usług i kontenerów, uruchamianie, zatrzymywanie, restart i usuwanie,
- logowanie użytkownika i trwałe dane w SQLite,
- automatyczne odświeżanie statusu panelu,
- API `/api/v1` z tokenami Bearer dla aplikacji desktop/mobile.

## Wymagania

- Docker Engine i dostęp do `/var/run/docker.sock`,
- Docker Compose v2 — tylko jeśli chcesz używać stacków,
- Docker lub Python 3.12 do uruchomienia bez kontenera.

## Uruchomienie przez Docker

Najprościej zbudować obraz lokalnie:

```bash
docker build -t orbit-control:local .
```

Uruchomienie:

```bash
docker run -d \
  --name orbit \
  --user root \
  -p 5001:5000 \
  -e ORBIT_SECRET_KEY="$(openssl rand -hex 32)" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v orbit-data:/app/data \
  --restart unless-stopped \
  orbit-control:local
```

Otwórz panel: <http://localhost:5001>

### Docker Compose

Plik `docker-compose.yml` jest już w repozytorium. Przed pierwszym uruchomieniem
utwórz lokalny plik `.env` na podstawie przykładu:

```bash
cp .env.example .env
sed -i "s/replace-with-a-long-random-secret/$(openssl rand -hex 32)/" .env
```

Na macOS, jeśli `sed` zgłosi błąd, otwórz `.env` i ręcznie wklej wynik:
`openssl rand -hex 32`.

Uruchom:

```bash
docker compose up -d --build
```

Zatrzymanie:

```bash
docker compose down
```

Logi:

```bash
docker compose logs -f orbit
```

> **Uwaga:** dostęp do Docker socket daje aplikacji uprawnienia do zarządzania Dockerem na hoście. Nie wystawiaj panelu publicznie bez HTTPS, ochrony sieciowej i silnego hasła.

## `ORBIT_SECRET_KEY` — co to jest?

To prywatny klucz używany przez Flask do podpisywania sesji logowania w panelu webowym. Nie jest tokenem Docker Hub i nie trzeba go nigdzie wcześniej pobierać — należy wygenerować własny losowy klucz.

Wygeneruj go na Linux/macOS:

```bash
openssl rand -hex 32
```

Następnie wpisz wynik do lokalnego pliku `.env`:

```env
ORBIT_SECRET_KEY=wynik-komendy-openssl
```

Plik `.env` jest ignorowany przez Git i powinien pozostać tylko na komputerze lub serwerze, na którym działa Orbit. Nie wysyłaj go na GitHub ani nie wklejaj sekretu do README. Po zmianie klucza aktywne sesje przeglądarki zostaną unieważnione.

## Pierwsze użycie

1. Uruchom Orbit i otwórz `http://localhost:5001`.
2. Załóż konto na stronie rejestracji.
3. Zaloguj się.
4. Wybierz kategorię zasobów i użyj przycisku `+ Dodaj`.

Jeżeli panel pokazuje `Docker Engine jest niedostępny`, sprawdź, czy kontener został uruchomiony z:

```bash
-v /var/run/docker.sock:/var/run/docker.sock
```

## API dla aplikacji desktopowej i mobilnej

API jest wersjonowane pod `/api/v1`. Do autoryzacji używa tokenów Bearer, niezależnych od ciasteczek przeglądarki.

### Pobranie tokenu

```bash
curl -X POST http://localhost:5001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"twoje-haslo"}'
```

Odpowiedź zawiera `token`. Przechowuj go bezpiecznie po stronie aplikacji.

### Odczyt statusu

```bash
curl http://localhost:5001/api/v1/status \
  -H "Authorization: Bearer TWÓJ_TOKEN"
```

### Dostępne endpointy

| Metoda | Endpoint | Opis |
|---|---|---|
| `POST` | `/api/v1/auth/login` | logowanie i wydanie tokenu |
| `POST` | `/api/v1/auth/revoke` | unieważnienie bieżącego tokenu |
| `GET` | `/api/v1/status` | pełny status Docker Engine |
| `GET` | `/api/v1/containers` | lista kontenerów |
| `POST` | `/api/v1/containers` | utworzenie kontenera |
| `POST` | `/api/v1/containers/{id}/start` | uruchomienie |
| `POST` | `/api/v1/containers/{id}/stop` | zatrzymanie |
| `POST` | `/api/v1/containers/{id}/restart` | restart |
| `DELETE` | `/api/v1/containers/{id}` | usunięcie |
| `GET` | `/api/v1/containers/{id}/logs` | logi |
| `POST` | `/api/v1/images/pull` | pobranie obrazu |
| `POST` | `/api/v1/images/build` | zbudowanie obrazu z Dockerfile |

W zakładce **Obrazy** można pobrać obraz z rejestru albo zbudować go z
Dockerfile. Dostępne są również szczegóły obrazu, usuwanie oraz czyszczenie
obrazów dangling, czyli bez tagów.

W zakładce **Stacki Compose** można wkleić YAML, uruchomić stack oraz zobaczyć
jego usługi, kontenery i statusy. Stacki wymagają Docker Compose v2 oraz
dostępu Orbit do Docker Engine.

Wszystkie endpointy poza logowaniem wymagają:

```text
Authorization: Bearer TWÓJ_TOKEN
```

## Uruchomienie lokalne bez Dockera

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export ORBIT_SECRET_KEY="$(openssl rand -hex 32)"
python app.py
```

## Konfiguracja

| Zmienna | Domyślna wartość | Znaczenie |
|---|---|---|
| `ORBIT_SECRET_KEY` | `change-me-in-production` | klucz sesji Flask; ustaw własny |
| `ORBIT_DATA_DIR` | `./data` | katalog bazy i stacków |
| `ORBIT_DB_PATH` | `$ORBIT_DATA_DIR/orbit.db` | ścieżka bazy SQLite |
| `PORT` | `5000` | port procesu aplikacji |

## Sprawdzanie działania

```bash
curl http://localhost:5001/health
```

Przykładowa odpowiedź:

```json
{"docker":true,"status":"ok"}
```

## Rozwój

Planowane rozszerzenia API obejmują statystyki zasobów, terminal exec, zarządzanie wieloma hostami Docker i powiadomienia.

## Licencja

Projekt jest dostępny na licencji MIT. Copyright © DevLabStudy.
