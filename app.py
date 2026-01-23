import docker
import sqlite3
import os
from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'orbit_secret_key_2026'

DB_PATH = '/app/orbit.db'


# ============ BAZA DANYCH ============

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    db = conn.cursor()

    # Użytkownicy
    db.execute('''CREATE TABLE IF NOT EXISTS users
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      email
                      TEXT
                      UNIQUE,
                      password
                      TEXT
                  )''')

    # Hosty Docker
    db.execute('''CREATE TABLE IF NOT EXISTS hosts
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      name
                      TEXT,
                      url
                      TEXT,
                      is_local
                      INTEGER
                      DEFAULT
                      0
                  )''')

    # Ustawienia powiadomień
    db.execute('''CREATE TABLE IF NOT EXISTS notifications
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      type
                      TEXT,
                      config
                      TEXT,
                      enabled
                      INTEGER
                      DEFAULT
                      1
                  )''')

    # Historia alertów
    db.execute('''CREATE TABLE IF NOT EXISTS alerts
                  (
                      id
                      INTEGER
                      PRIMARY
                      KEY
                      AUTOINCREMENT,
                      host_id
                      INTEGER,
                      container_name
                      TEXT,
                      message
                      TEXT,
                      timestamp
                      DATETIME
                      DEFAULT
                      CURRENT_TIMESTAMP
                  )''')

    # Dodaj localhost jako domyślny host jeśli nie istnieje
    db.execute("SELECT id FROM hosts WHERE is_local = 1")
    if not db.fetchone():
        db.execute("INSERT INTO hosts (name, url, is_local) VALUES (?, ?, ?)",
                   ("Local Docker", "unix://var/run/docker.sock", 1))

    conn.commit()
    conn.close()
    print("✅ Baza danych zainicjalizowana")


init_db()


# ============ DOCKER CLIENT ============

def get_docker_client(host_id=None):
    """Pobiera klienta Docker dla danego hosta"""
    try:
        if host_id:
            conn = get_db()
            host = conn.execute("SELECT url FROM hosts WHERE id = ?", (host_id,)).fetchone()
            conn.close()
            if host:
                return docker.DockerClient(base_url=host['url'])
        return docker.from_env()
    except Exception as e:
        print(f"⚠️ Błąd połączenia z Dockerem: {e}")
        return None


# Domyślny klient
client = get_docker_client()
if client:
    print("✅ Połączono z Docker Engine")


# ============ ROUTING - AUTH ============

@app.route('/')
def home():
    if 'user' in session:
        return render_template('index.html')
    return render_template('login.html')


@app.route('/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"status": "error", "message": "Uzupełnij wszystkie pola"}), 400

    hashed_pw = generate_password_hash(password)
    try:
        conn = get_db()
        conn.execute("INSERT INTO users (email, password) VALUES (?, ?)", (email, hashed_pw))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok", "message": "Konto utworzone! Możesz się zalogować."})
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "Ten email jest już zarejestrowany"}), 400


@app.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"status": "error", "message": "Uzupełnij wszystkie pola"}), 400

    conn = get_db()
    user = conn.execute("SELECT password FROM users WHERE email=?", (email,)).fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):
        session['user'] = email
        return jsonify({"status": "ok"})
    return jsonify({"status": "error", "message": "Błędne dane logowania"}), 401


@app.route('/logout')
def logout():
    session.pop('user', None)
    return jsonify({"status": "ok"})


# ============ ROUTING - STATUS ============

@app.route('/status')
def status():
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401

    if client is None:
        return jsonify({"error": "Docker niedostępny"}), 503

    try:
        all_containers = client.containers.list(all=True)
        all_images = client.images.list()
        all_volumes = client.volumes.list()
        all_networks = client.networks.list()

        containers = []
        for c in all_containers:
            c.reload()
            state = c.attrs['State']

            if state.get('Running'):
                status = 'running'
            elif state.get('Paused'):
                status = 'paused'
            elif state.get('Restarting'):
                status = 'restarting'
            elif state.get('Dead'):
                status = 'dead'
            else:
                status = 'stopped'

            containers.append({
                "id": c.short_id,
                "name": c.name,
                "status": status,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id
            })

        images = []
        for img in all_images:
            size_mb = round(img.attrs['Size'] / (1024 * 1024), 1)
            images.append({
                "id": img.short_id.replace("sha256:", ""),
                "tags": img.tags if img.tags else ["<none>:<none>"],
                "size": f"{size_mb} MB"
            })

        volumes = []
        for vol in all_volumes:
            volumes.append({
                "name": vol.name,
                "driver": vol.attrs.get('Driver', 'unknown'),
                "mountpoint": vol.attrs.get('Mountpoint', '')[:50]
            })

        networks = []
        for net in all_networks:
            networks.append({
                "id": net.short_id,
                "name": net.name,
                "driver": net.attrs.get('Driver', 'unknown'),
                "scope": net.attrs.get('Scope', 'unknown')
            })

        return jsonify({
            "counts": {
                "containers": len(all_containers),
                "images": len(all_images),
                "stacks": 0,
                "volumes": len(all_volumes),
                "networks": len(all_networks)
            },
            "containers": containers,
            "images": images,
            "volumes": volumes,
            "networks": networks,
            "alerts_count": sum(1 for c in containers if c['status'] != 'running')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============ KONTENERY - AKCJE ============

@app.route('/container/<container_id>/start', methods=['POST'])
def container_start(container_id):
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        container = client.containers.get(container_id)
        container.start()
        return jsonify({"status": "ok", "message": f"Kontener {container.name} uruchomiony"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/container/<container_id>/stop', methods=['POST'])
def container_stop(container_id):
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        container = client.containers.get(container_id)
        container.stop()
        return jsonify({"status": "ok", "message": f"Kontener {container.name} zatrzymany"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/container/<container_id>/restart', methods=['POST'])
def container_restart(container_id):
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        container = client.containers.get(container_id)
        container.restart()
        return jsonify({"status": "ok", "message": f"Kontener {container.name} zrestartowany"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/container/<container_id>/remove', methods=['POST'])
def container_remove(container_id):
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        container = client.containers.get(container_id)
        name = container.name
        container.remove(force=True)
        return jsonify({"status": "ok", "message": f"Kontener {name} usunięty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ KONTENERY - TWORZENIE ============

@app.route('/container/create', methods=['POST'])
def container_create():
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401

    try:
        data = request.json
        image = data.get('image')
        name = data.get('name')
        ports = data.get('ports', {})  # {"80/tcp": 8080}
        env = data.get('env', [])  # ["KEY=value"]
        volumes = data.get('volumes', {})  # {"/host/path": {"bind": "/container/path", "mode": "rw"}}
        restart_policy = data.get('restart_policy', 'no')
        network = data.get('network', None)

        if not image:
            return jsonify({"status": "error", "message": "Obraz jest wymagany"}), 400

        # Spróbuj pobrać obraz jeśli nie istnieje
        try:
            client.images.get(image)
        except docker.errors.ImageNotFound:
            print(f"📥 Pobieranie obrazu: {image}")
            client.images.pull(image)

        # Przygotuj port bindings
        port_bindings = {}
        ports_config = {}
        if ports:
            for container_port, host_port in ports.items():
                port_bindings[container_port] = host_port
                ports_config[container_port] = {}

        # Restart policy
        restart_config = {"Name": restart_policy}
        if restart_policy == "on-failure":
            restart_config["MaximumRetryCount"] = 5

        # Utwórz kontener
        container = client.containers.run(
            image=image,
            name=name if name else None,
            ports=port_bindings if port_bindings else None,
            environment=env if env else None,
            volumes=volumes if volumes else None,
            restart_policy=restart_config,
            network=network if network else None,
            detach=True
        )

        return jsonify({
            "status": "ok",
            "message": f"Kontener {container.name} utworzony i uruchomiony",
            "id": container.short_id
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ OBRAZY - PULL ============

@app.route('/image/pull', methods=['POST'])
def image_pull():
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401

    try:
        data = request.json
        image = data.get('image')

        if not image:
            return jsonify({"status": "error", "message": "Nazwa obrazu jest wymagana"}), 400

        print(f"📥 Pobieranie obrazu: {image}")
        client.images.pull(image)

        return jsonify({"status": "ok", "message": f"Obraz {image} pobrany"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/image/<image_id>/remove', methods=['POST'])
def image_remove(image_id):
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        client.images.remove(image_id, force=True)
        return jsonify({"status": "ok", "message": f"Obraz usunięty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ SIECI ============

@app.route('/network/create', methods=['POST'])
def network_create():
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        data = request.json
        name = data.get('name')
        driver = data.get('driver', 'bridge')

        if not name:
            return jsonify({"status": "error", "message": "Nazwa sieci jest wymagana"}), 400

        client.networks.create(name=name, driver=driver)
        return jsonify({"status": "ok", "message": f"Sieć {name} utworzona"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/network/<network_id>/remove', methods=['POST'])
def network_remove(network_id):
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        network = client.networks.get(network_id)
        name = network.name
        network.remove()
        return jsonify({"status": "ok", "message": f"Sieć {name} usunięta"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ VOLUMES ============

@app.route('/volume/create', methods=['POST'])
def volume_create():
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        data = request.json
        name = data.get('name')

        if not name:
            return jsonify({"status": "error", "message": "Nazwa volume jest wymagana"}), 400

        client.volumes.create(name=name)
        return jsonify({"status": "ok", "message": f"Volume {name} utworzony"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/volume/<volume_name>/remove', methods=['POST'])
def volume_remove(volume_name):
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401
    try:
        volume = client.volumes.get(volume_name)
        volume.remove()
        return jsonify({"status": "ok", "message": f"Volume {volume_name} usunięty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ HOSTY (przygotowane na multi-host) ============

@app.route('/hosts')
def get_hosts():
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    hosts = conn.execute("SELECT * FROM hosts").fetchall()
    conn.close()

    return jsonify([dict(h) for h in hosts])


@app.route('/host/add', methods=['POST'])
def add_host():
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401

    try:
        data = request.json
        name = data.get('name')
        url = data.get('url')  # np. tcp://192.168.0.100:2375

        if not name or not url:
            return jsonify({"status": "error", "message": "Nazwa i URL są wymagane"}), 400

        # Sprawdź połączenie
        try:
            test_client = docker.DockerClient(base_url=url)
            test_client.ping()
        except Exception as e:
            return jsonify({"status": "error", "message": f"Nie można połączyć: {e}"}), 400

        conn = get_db()
        conn.execute("INSERT INTO hosts (name, url, is_local) VALUES (?, ?, 0)", (name, url))
        conn.commit()
        conn.close()

        return jsonify({"status": "ok", "message": f"Host {name} dodany"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/host/<int:host_id>/remove', methods=['POST'])
def remove_host(host_id):
    if 'user' not in session:
        return jsonify({"error": "unauthorized"}), 401

    try:
        conn = get_db()
        # Nie pozwól usunąć lokalnego hosta
        host = conn.execute("SELECT is_local FROM hosts WHERE id = ?", (host_id,)).fetchone()
        if host and host['is_local']:
            return jsonify({"status": "error", "message": "Nie można usunąć lokalnego hosta"}), 400

        conn.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
        conn.commit()
        conn.close()

        return jsonify({"status": "ok", "message": "Host usunięty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)