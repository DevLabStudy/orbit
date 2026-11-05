import os
import re
import secrets
import hashlib
import shutil
import sqlite3
import subprocess
import tempfile
from functools import wraps
from pathlib import Path

import docker
import yaml
from docker.errors import APIError, ImageNotFound, NotFound
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ORBIT_DATA_DIR", BASE_DIR / "data"))
STACKS_PATH = DATA_DIR / "stacks"
DB_PATH = Path(os.environ.get("ORBIT_DB_PATH", DATA_DIR / "orbit.db"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STACKS_PATH.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("ORBIT_SECRET_KEY", "change-me-in-production")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

VERSION = "2.0.0"
GITHUB_REPO = "DevLabStudy/orbit"
SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")
IMAGE_TAG = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}(?::[a-zA-Z0-9][a-zA-Z0-9._-]{0,127})?$")


def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with get_db() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS api_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_used_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )"""
        )


init_db()


def docker_client():
    """Return a fresh client so a temporary Docker outage can recover."""
    try:
        client = docker.from_env(timeout=10)
        client.ping()
        return client
    except (docker.errors.DockerException, OSError):
        return None


def require_login(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)

    return wrapped


def json_error(message, status=400):
    return jsonify(
        {
            "status": "error",
            "message": message,
            "help_url": "https://www.devlabstudy.ovh",
            "help_text": "Potrzebujesz pomocy? devlabstudy.ovh",
        }
    ), status


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bearer_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if len(token) < 32:
        return None
    with get_db() as connection:
        user = connection.execute(
            """SELECT users.id, users.email, api_tokens.id AS token_id
               FROM api_tokens JOIN users ON users.id = api_tokens.user_id
               WHERE api_tokens.token_hash = ?""",
            (hash_token(token),),
        ).fetchone()
        if user:
            connection.execute(
                "UPDATE api_tokens SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
                (user["token_id"],),
            )
    return user


def require_api_token(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = bearer_user()
        if not user:
            return json_error("Wymagany jest prawidłowy token Bearer", 401)
        return view(*args, **kwargs)

    return wrapped


def container_status(container):
    state = container.attrs.get("State", {})
    if state.get("Running"):
        return "running"
    if state.get("Paused"):
        return "paused"
    if state.get("Restarting"):
        return "restarting"
    if state.get("Dead"):
        return "dead"
    return "stopped"


def image_name(container):
    tags = getattr(container.image, "tags", [])
    return tags[0] if tags else container.image.short_id


def format_ports(container):
    ports = []
    for container_port, bindings in (container.attrs.get("NetworkSettings", {}).get("Ports") or {}).items():
        if not bindings:
            ports.append({"container": container_port, "host": None, "url": None})
            continue
        for binding in bindings:
            host = f"{binding.get('HostIp', '0.0.0.0')}:{binding.get('HostPort')}"
            ports.append(
                {
                    "container": container_port,
                    "host": host,
                    "url": f"http://{host}" if container_port.startswith(("80/", "443/")) else None,
                }
            )
    return ports


def serialize_container(container):
    container.reload()
    return {
        "id": container.short_id,
        "name": container.name,
        "status": container_status(container),
        "image": image_name(container),
        "ports": format_ports(container),
        "created": container.attrs.get("Created"),
    }


def get_stacks(client):
    stacks = {}
    for container in client.containers.list(all=True):
        project = container.labels.get("com.docker.compose.project")
        if not project:
            continue
        stack = stacks.setdefault(
            project,
            {
                "name": project,
                "containers": [],
                "path": container.labels.get("com.docker.compose.project.working_dir", ""),
            },
        )
        stack["containers"].append(
            {
                "name": container.name,
                "status": container_status(container),
                "image": image_name(container),
                "ports": format_ports(container),
            }
        )
    return list(stacks.values())


def get_client_or_error():
    client = docker_client()
    if client is None:
        return None, json_error("Docker Engine jest niedostępny", 503)
    return client, None


@app.route("/")
def home():
    return render_template("index.html" if "user" in session else "login.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if not email or not password:
        return json_error("Uzupełnij wszystkie pola")
    with get_db() as connection:
        user = connection.execute(
            "SELECT password FROM users WHERE email = ?", (email,)
        ).fetchone()
    if not user or not check_password_hash(user["password"], password):
        return json_error("Błędne dane logowania", 401)
    session["user"] = email
    return jsonify({"status": "ok"})


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if "@" not in email or len(password) < 8:
        return json_error("Podaj poprawny email i hasło o długości minimum 8 znaków")
    try:
        with get_db() as connection:
            connection.execute(
                "INSERT INTO users (email, password) VALUES (?, ?)",
                (email, generate_password_hash(password)),
            )
    except sqlite3.IntegrityError:
        return json_error("Ten email jest już zarejestrowany")
    return jsonify({"status": "ok", "message": "Konto utworzone. Możesz się zalogować."})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.post("/api/v1/auth/login")
def api_login():
    """Authenticate native clients without relying on browser cookies."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    with get_db() as connection:
        user = connection.execute(
            "SELECT id, email, password FROM users WHERE email = ?", (email,)
        ).fetchone()
    if not user or not check_password_hash(user["password"], password):
        return json_error("Błędne dane logowania", 401)
    token = secrets.token_urlsafe(48)
    with get_db() as connection:
        connection.execute(
            "INSERT INTO api_tokens (user_id, token_hash) VALUES (?, ?)",
            (user["id"], hash_token(token)),
        )
    return jsonify({"token": token, "token_type": "Bearer", "user": {"email": user["email"]}})


@app.post("/api/v1/auth/revoke")
@require_api_token
def api_revoke():
    header = request.headers.get("Authorization", "")
    with get_db() as connection:
        connection.execute(
            "DELETE FROM api_tokens WHERE token_hash = ?", (hash_token(header[7:].strip()),)
        )
    return jsonify({"status": "ok", "message": "Token unieważniony"})


@app.get("/api/v1/status")
@require_api_token
def api_status():
    return status.__wrapped__()


@app.get("/api/v1/containers")
@require_api_token
def api_containers():
    client, error = get_client_or_error()
    if error:
        return error
    try:
        return jsonify({"containers": [serialize_container(item) for item in client.containers.list(all=True)]})
    except APIError as exc:
        return json_error(f"Nie udało się odczytać kontenerów: {exc.explanation}", 502)


@app.post("/api/v1/containers")
@require_api_token
def api_create_container():
    return container_create.__wrapped__()


@app.post("/api/v1/containers/<container_id>/<action>")
@require_api_token
def api_container_action(container_id, action):
    if action not in {"start", "stop", "restart"}:
        return json_error("Nieprawidłowa operacja")
    return container_action(container_id, action)


@app.delete("/api/v1/containers/<container_id>")
@require_api_token
def api_delete_container(container_id):
    return container_remove.__wrapped__(container_id)


@app.get("/api/v1/containers/<container_id>/logs")
@require_api_token
def api_container_logs(container_id):
    return container_logs.__wrapped__(container_id)


@app.post("/api/v1/images/pull")
@require_api_token
def api_pull_image():
    return image_pull.__wrapped__()


@app.post("/api/v1/images/build")
@require_api_token
def api_build_image():
    return image_build.__wrapped__()


@app.route("/api/version")
def get_version():
    return jsonify({"current": VERSION, "github_repo": f"https://github.com/{GITHUB_REPO}"})


@app.route("/status")
@require_login
def status():
    client, error = get_client_or_error()
    if error:
        return error
    try:
        all_containers = client.containers.list(all=True)
        all_images = client.images.list()
        all_volumes = client.volumes.list()
        all_networks = client.networks.list()
        containers = [serialize_container(item) for item in all_containers]
        images = [
            {
                "id": item.short_id.replace("sha256:", ""),
                "tags": item.tags or ["<none>:<none>"],
                "size": f"{round(item.attrs.get('Size', 0) / 1024 / 1024, 1)} MB",
                "created": item.attrs.get("Created"),
            }
            for item in all_images
        ]
        volumes = [
            {
                "name": item.name,
                "driver": item.attrs.get("Driver", "unknown"),
                "mountpoint": item.attrs.get("Mountpoint", ""),
            }
            for item in all_volumes
        ]
        networks = [
            {
                "id": item.short_id,
                "name": item.name,
                "driver": item.attrs.get("Driver", "unknown"),
                "scope": item.attrs.get("Scope", "unknown"),
            }
            for item in all_networks
        ]
        stacks = get_stacks(client)
        return jsonify(
            {
                "counts": {
                    "containers": len(all_containers),
                    "images": len(all_images),
                    "stacks": len(stacks),
                    "volumes": len(all_volumes),
                    "networks": len(all_networks),
                },
                "containers": containers,
                "images": images,
                "volumes": volumes,
                "networks": networks,
                "stacks": stacks,
            }
        )
    except APIError as exc:
        return json_error(f"Nie udało się odczytać danych Dockera: {exc.explanation}", 502)


def container_action(container_id, action):
    client, error = get_client_or_error()
    if error:
        return error
    try:
        container = client.containers.get(container_id)
        getattr(container, action)()
        return jsonify({"status": "ok", "message": f"Kontener {container.name}: {action}"})
    except NotFound:
        return json_error("Nie znaleziono kontenera", 404)
    except APIError as exc:
        return json_error(f"Docker odrzucił operację: {exc.explanation}", 409)


@app.route("/container/<container_id>/<action>", methods=["POST"])
@require_login
def container_operation(container_id, action):
    if action not in {"start", "stop", "restart"}:
        return json_error("Nieprawidłowa operacja")
    return container_action(container_id, action)


@app.route("/container/<container_id>/remove", methods=["POST"])
@require_login
def container_remove(container_id):
    client, error = get_client_or_error()
    if error:
        return error
    try:
        container = client.containers.get(container_id)
        name = container.name
        container.remove(force=True)
        return jsonify({"status": "ok", "message": f"Kontener {name} usunięty"})
    except NotFound:
        return json_error("Nie znaleziono kontenera", 404)
    except APIError as exc:
        return json_error(f"Nie udało się usunąć kontenera: {exc.explanation}", 409)


@app.route("/container/<container_id>/logs")
@require_login
def container_logs(container_id):
    client, error = get_client_or_error()
    if error:
        return error
    try:
        logs = client.containers.get(container_id).logs(tail=200, timestamps=True)
        return jsonify({"status": "ok", "logs": logs.decode("utf-8", errors="replace")})
    except NotFound:
        return json_error("Nie znaleziono kontenera", 404)
    except APIError as exc:
        return json_error(f"Nie udało się pobrać logów: {exc.explanation}", 502)


@app.route("/container/<container_id>/inspect")
@require_login
def container_inspect(container_id):
    client, error = get_client_or_error()
    if error:
        return error
    try:
        container = client.containers.get(container_id)
        container.reload()
        attrs = container.attrs
        config = attrs.get("Config", {})
        host_config = attrs.get("HostConfig", {})
        mounts = [
            {
                "source": mount.get("Source"),
                "destination": mount.get("Destination"),
                "mode": mount.get("Mode"),
                "type": mount.get("Type"),
            }
            for mount in attrs.get("Mounts", [])
        ]
        return jsonify(
            {
                "name": container.name,
                "id": container.short_id,
                "status": container_status(container),
                "image": image_name(container),
                "command": config.get("Cmd") or [],
                "entrypoint": config.get("Entrypoint") or [],
                "environment": config.get("Env") or [],
                "mounts": mounts,
                "networks": list((attrs.get("NetworkSettings", {}).get("Networks") or {}).keys()),
                "restart_policy": host_config.get("RestartPolicy", {}),
                "ports": format_ports(container),
                "labels": container.labels,
            }
        )
    except NotFound:
        return json_error("Nie znaleziono kontenera", 404)
    except APIError as exc:
        return json_error(f"Nie udało się odczytać konfiguracji: {exc.explanation}", 502)


@app.route("/container/create", methods=["POST"])
@require_login
def container_create():
    data = request.get_json(silent=True) or {}
    image = str(data.get("image", "")).strip()
    name = str(data.get("name", "")).strip() or None
    if not image:
        return json_error("Obraz jest wymagany")
    if name and not SAFE_NAME.fullmatch(name):
        return json_error("Nazwa kontenera zawiera niedozwolone znaki")
    restart_policy = data.get("restart_policy", "no")
    if restart_policy not in {"no", "always", "on-failure", "unless-stopped"}:
        return json_error("Nieprawidłowa polityka restartu")
    client, error = get_client_or_error()
    if error:
        return error
    try:
        try:
            client.images.get(image)
        except ImageNotFound:
            client.images.pull(image)
        ports = data.get("ports") or {}
        if not isinstance(ports, dict):
            return json_error("Porty muszą być mapą portu kontenera na port hosta")
        normalized_ports = {}
        for container_port, host_port in ports.items():
            if not str(container_port).isdigit() or not str(host_port).isdigit():
                return json_error("Porty muszą być liczbami")
            normalized_ports[f"{container_port}/tcp"] = int(host_port)
        environment = data.get("env") or []
        if isinstance(environment, dict):
            environment = [f"{key}={value}" for key, value in environment.items()]
        if not isinstance(environment, list):
            return json_error("Zmienne środowiskowe muszą być listą")
        kwargs = {
            "image": image,
            "name": name,
            "ports": normalized_ports or None,
            "environment": environment or None,
            "restart_policy": {"Name": restart_policy},
            "detach": True,
        }
        network = str(data.get("network", "")).strip()
        if network:
            kwargs["network"] = network
        container = client.containers.run(**kwargs)
        return jsonify(
            {
                "status": "ok",
                "message": f"Kontener {container.name} utworzony i uruchomiony",
                "id": container.short_id,
            }
        )
    except (ImageNotFound, APIError) as exc:
        message = getattr(exc, "explanation", str(exc))
        return json_error(f"Nie udało się utworzyć kontenera: {message}", 409)


@app.route("/image/pull", methods=["POST"])
@require_login
def image_pull():
    data = request.get_json(silent=True) or {}
    image = str(data.get("image", "")).strip()
    if not image:
        return json_error("Nazwa obrazu jest wymagana")
    client, error = get_client_or_error()
    if error:
        return error
    try:
        client.images.pull(image)
        return jsonify({"status": "ok", "message": f"Obraz {image} pobrany"})
    except APIError as exc:
        return json_error(f"Nie udało się pobrać obrazu: {exc.explanation}", 409)


@app.route("/image/build", methods=["POST"])
@require_login
def image_build():
    data = request.get_json(silent=True) or {}
    tag = str(data.get("tag", "")).strip()
    dockerfile = str(data.get("dockerfile", "")).strip()
    if not IMAGE_TAG.fullmatch(tag) or not dockerfile:
        return json_error("Podaj poprawny tag obrazu i zawartość Dockerfile")
    if len(dockerfile) > 100_000:
        return json_error("Dockerfile jest zbyt duży")
    client, error = get_client_or_error()
    if error:
        return error
    try:
        with tempfile.TemporaryDirectory(prefix="orbit-build-") as build_dir:
            Path(build_dir, "Dockerfile").write_text(dockerfile, encoding="utf-8")
            image, logs = client.images.build(path=build_dir, tag=tag, rm=True)
        return jsonify(
            {
                "status": "ok",
                "message": f"Obraz {tag} zbudowany",
                "id": image.short_id,
                "logs": "\n".join(
                    item.get("stream", "").strip()
                    for item in logs
                    if isinstance(item, dict) and item.get("stream")
                ),
            }
        )
    except (APIError, docker.errors.BuildError) as exc:
        return json_error(f"Nie udało się zbudować obrazu: {getattr(exc, 'explanation', str(exc))}", 409)


@app.route("/image/prune", methods=["POST"])
@require_login
def image_prune():
    client, error = get_client_or_error()
    if error:
        return error
    try:
        result = client.images.prune(filters={"dangling": True})
        reclaimed = round(result.get("SpaceReclaimed", 0) / 1024 / 1024, 1)
        return jsonify(
            {
                "status": "ok",
                "message": f"Usunięto nieużywane obrazy ({reclaimed} MB)",
                "deleted": result.get("ImagesDeleted") or [],
            }
        )
    except APIError as exc:
        return json_error(f"Nie udało się wyczyścić obrazów: {exc.explanation}", 409)


@app.route("/image/<path:image_id>/remove", methods=["POST"])
@require_login
def image_remove(image_id):
    client, error = get_client_or_error()
    if error:
        return error
    try:
        client.images.remove(image_id, force=True)
        return jsonify({"status": "ok", "message": "Obraz usunięty"})
    except APIError as exc:
        return json_error(f"Nie udało się usunąć obrazu: {exc.explanation}", 409)


@app.route("/image/<path:image_id>/inspect")
@require_login
def image_inspect(image_id):
    client, error = get_client_or_error()
    if error:
        return error
    try:
        image = client.images.get(image_id)
        return jsonify(
            {
                "id": image.short_id,
                "tags": image.tags or ["<none>:<none>"],
                "size": image.attrs.get("Size", 0),
                "created": image.attrs.get("Created"),
                "layers": len(image.attrs.get("RootFS", {}).get("Layers", [])),
                "architecture": image.attrs.get("Architecture"),
                "os": image.attrs.get("Os"),
            }
        )
    except NotFound:
        return json_error("Nie znaleziono obrazu", 404)
    except APIError as exc:
        return json_error(f"Nie udało się odczytać obrazu: {exc.explanation}", 502)


@app.route("/network/create", methods=["POST"])
@require_login
def network_create():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    driver = str(data.get("driver", "bridge")).strip()
    if not SAFE_NAME.fullmatch(name):
        return json_error("Nieprawidłowa nazwa sieci")
    if driver not in {"bridge", "host", "overlay", "macvlan"}:
        return json_error("Nieprawidłowy driver sieci")
    client, error = get_client_or_error()
    if error:
        return error
    try:
        client.networks.create(name=name, driver=driver)
        return jsonify({"status": "ok", "message": f"Sieć {name} utworzona"})
    except APIError as exc:
        return json_error(f"Nie udało się utworzyć sieci: {exc.explanation}", 409)


@app.route("/network/<network_id>/remove", methods=["POST"])
@require_login
def network_remove(network_id):
    client, error = get_client_or_error()
    if error:
        return error
    try:
        network = client.networks.get(network_id)
        network.remove()
        return jsonify({"status": "ok", "message": "Sieć usunięta"})
    except (NotFound, APIError) as exc:
        return json_error(f"Nie udało się usunąć sieci: {getattr(exc, 'explanation', str(exc))}", 409)


@app.route("/volume/create", methods=["POST"])
@require_login
def volume_create():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not SAFE_NAME.fullmatch(name):
        return json_error("Nieprawidłowa nazwa volume")
    client, error = get_client_or_error()
    if error:
        return error
    try:
        client.volumes.create(name=name)
        return jsonify({"status": "ok", "message": f"Volume {name} utworzony"})
    except APIError as exc:
        return json_error(f"Nie udało się utworzyć volume: {exc.explanation}", 409)


@app.route("/volume/<path:volume_name>/remove", methods=["POST"])
@require_login
def volume_remove(volume_name):
    client, error = get_client_or_error()
    if error:
        return error
    try:
        client.volumes.get(volume_name).remove()
        return jsonify({"status": "ok", "message": "Volume usunięty"})
    except (NotFound, APIError) as exc:
        return json_error(f"Nie udało się usunąć volume: {getattr(exc, 'explanation', str(exc))}", 409)


def compose_command(name, action):
    compose_file = STACKS_PATH / name / "docker-compose.yml"
    if not compose_file.is_file():
        return None, "Nie znaleziono pliku stacka"
    if shutil.which("docker") is None:
        return None, "W obrazie nie ma polecenia docker compose"
    return ["docker", "compose", "-p", name, "-f", str(compose_file), action], None


@app.route("/stack/create", methods=["POST"])
@require_login
def stack_create():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    compose_content = str(data.get("compose", "")).strip()
    if not SAFE_NAME.fullmatch(name) or not compose_content:
        return json_error("Podaj poprawną nazwę i konfigurację stacka")
    try:
        parsed = yaml.safe_load(compose_content)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("services"), dict):
            return json_error("Compose musi zawierać sekcję services")
    except yaml.YAMLError as exc:
        return json_error(f"Nieprawidłowy YAML: {exc}")
    stack_dir = STACKS_PATH / name
    stack_dir.mkdir(parents=True, exist_ok=True)
    compose_file = stack_dir / "docker-compose.yml"
    compose_file.write_text(compose_content, encoding="utf-8")
    command, error_message = compose_command(name, "up")
    if not command:
        return json_error(error_message, 503)
    result = subprocess.run(command + ["-d"], capture_output=True, text=True, timeout=120)
    if result.returncode:
        return json_error(result.stderr.strip() or "Compose nie uruchomił stacka", 409)
    return jsonify({"status": "ok", "message": f"Stack {name} uruchomiony"})


@app.route("/stack/<name>/<action>", methods=["POST"])
@require_login
def stack_operation(name, action):
    if not SAFE_NAME.fullmatch(name) or action not in {"start", "stop", "restart", "remove"}:
        return json_error("Nieprawidłowy stack lub operacja")
    command, error_message = compose_command(name, "down" if action == "remove" else action)
    if command:
        result = subprocess.run(
            command + (["-v"] if action == "remove" else []),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode:
            return json_error(result.stderr.strip() or "Operacja Compose nie powiodła się", 409)
        if action == "remove":
            shutil.rmtree(STACKS_PATH / name, ignore_errors=True)
        return jsonify({"status": "ok", "message": f"Stack {name}: {action}"})
    if action == "remove":
        return json_error(error_message, 503)
    return json_error(error_message, 404)


@app.route("/stack/<name>/details")
@require_login
def stack_details(name):
    if not SAFE_NAME.fullmatch(name):
        return json_error("Nieprawidłowa nazwa stacka")
    compose_file = STACKS_PATH / name / "docker-compose.yml"
    if not compose_file.is_file():
        return json_error("Nie znaleziono pliku Compose dla tego stacka", 404)
    try:
        compose = compose_file.read_text(encoding="utf-8")
        parsed = yaml.safe_load(compose) or {}
        services = parsed.get("services", {})
        return jsonify(
            {
                "name": name,
                "path": str(compose_file),
                "compose": compose,
                "services": [
                    {
                        "name": service_name,
                        "image": service.get("image"),
                        "build": service.get("build"),
                        "ports": service.get("ports", []),
                        "volumes": service.get("volumes", []),
                        "depends_on": service.get("depends_on", []),
                    }
                    for service_name, service in services.items()
                    if isinstance(service, dict)
                ],
            }
        )
    except (OSError, yaml.YAMLError) as exc:
        return json_error(f"Nie udało się odczytać konfiguracji stacka: {exc}", 500)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "docker": docker_client() is not None})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
