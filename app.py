import docker
import sqlite3
import os
import yaml
import subprocess
from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'orbit_secret_key_2026'

VERSION = "1.1.0"
GITHUB_REPO = "TobiMessi/orbit"

DB_PATH = '/app/orbit.db'
STACKS_PATH = '/app/stacks'

os.makedirs(STACKS_PATH, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    db = conn.cursor()
    db.execute('''CREATE TABLE IF NOT EXISTS users
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   email TEXT UNIQUE,
                   password TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS hosts
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT, url TEXT, is_local INTEGER DEFAULT 0)''')
    db.execute("SELECT id FROM hosts WHERE is_local = 1")
    if not db.fetchone():
        db.execute("INSERT INTO hosts (name, url, is_local) VALUES (?, ?, ?)",
                   ("Local Docker", "unix://var/run/docker.sock", 1))
    conn.commit()
    conn.close()
    print("✅ Baza danych zainicjalizowana")


init_db()


def get_docker_client(host_id=None):
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


client = get_docker_client()
if client:
    print("✅ Połączono z Docker Engine")


def get_stacks():
    stacks = {}
    try:
        containers = client.containers.list(all=True)
        for c in containers:
            labels = c.labels
            project = labels.get('com.docker.compose.project')
            if project:
                if project not in stacks:
                    stacks[project] = {'name': project, 'containers': []}
                c.reload()
                state = c.attrs['State']
                status = 'running' if state.get('Running') else 'stopped'
                stacks[project]['containers'].append({'name': c.name, 'status': status})
    except Exception as e:
        print(f"Błąd pobierania stacków: {e}")
    return list(stacks.values())


@app.route('/')
def home():
    if 'user' in session:
        return render_template('index.html')
    return render_template('login.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
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
        return jsonify({"status": "ok", "message": "Konto utworzone!"})
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "Ten email jest już zarejestrowany"}), 400


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


@app.route('/api/version')
def get_version():
    return jsonify({'current': VERSION, 'github_repo': f'https://github.com/{GITHUB_REPO}'})


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
        all_stacks = get_stacks()

        containers = []
        for c in all_containers:
            c.reload()
            state = c.attrs['State']
            if state.get('Running'): status = 'running'
            elif state.get('Paused'): status = 'paused'
            elif state.get('Restarting'): status = 'restarting'
            else: status = 'stopped'
            containers.append({
                "id": c.short_id, "name": c.name, "status": status,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id
            })

        images = [{"id": img.short_id.replace("sha256:", ""),
                   "tags": img.tags if img.tags else ["<none>:<none>"],
                   "size": f"{round(img.attrs['Size'] / (1024 * 1024), 1)} MB"} for img in all_images]

        volumes = [{"name": vol.name, "driver": vol.attrs.get('Driver', 'unknown'),
                    "mountpoint": vol.attrs.get('Mountpoint', '')[:50]} for vol in all_volumes]

        networks = [{"id": net.short_id, "name": net.name,
                     "driver": net.attrs.get('Driver', 'unknown'),
                     "scope": net.attrs.get('Scope', 'unknown')} for net in all_networks]

        return jsonify({
            "counts": {"containers": len(all_containers), "images": len(all_images),
                       "stacks": len(all_stacks), "volumes": len(all_volumes), "networks": len(all_networks)},
            "containers": containers, "images": images, "volumes": volumes,
            "networks": networks, "stacks": all_stacks
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/container/<container_id>/start', methods=['POST'])
def container_start(container_id):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        container = client.containers.get(container_id)
        container.start()
        return jsonify({"status": "ok", "message": f"Kontener {container.name} uruchomiony"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/container/<container_id>/stop', methods=['POST'])
def container_stop(container_id):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        container = client.containers.get(container_id)
        container.stop()
        return jsonify({"status": "ok", "message": f"Kontener {container.name} zatrzymany"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/container/<container_id>/restart', methods=['POST'])
def container_restart(container_id):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        container = client.containers.get(container_id)
        container.restart()
        return jsonify({"status": "ok", "message": f"Kontener {container.name} zrestartowany"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/container/<container_id>/remove', methods=['POST'])
def container_remove(container_id):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        container = client.containers.get(container_id)
        name = container.name
        container.remove(force=True)
        return jsonify({"status": "ok", "message": f"Kontener {name} usunięty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/container/<container_id>/logs', methods=['GET'])
def container_logs(container_id):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        container = client.containers.get(container_id)
        logs = container.logs(tail=100, timestamps=True).decode('utf-8', errors='ignore')
        return jsonify({"status": "ok", "logs": logs})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/container/create', methods=['POST'])
def container_create():
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        data = request.json
        image = data.get('image')
        if not image: return jsonify({"status": "error", "message": "Obraz jest wymagany"}), 400

        try: client.images.get(image)
        except docker.errors.ImageNotFound: client.images.pull(image)

        port_bindings = {}
        if data.get('ports'):
            for cp, hp in data['ports'].items():
                port_bindings[cp] = hp

        restart_config = {"Name": data.get('restart_policy', 'no')}
        if restart_config["Name"] == "on-failure":
            restart_config["MaximumRetryCount"] = 5

        container = client.containers.run(
            image=image, name=data.get('name'), ports=port_bindings or None,
            environment=data.get('env') or None, restart_policy=restart_config,
            network=data.get('network') or None, detach=True
        )
        return jsonify({"status": "ok", "message": f"Kontener {container.name} utworzony", "id": container.short_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/image/pull', methods=['POST'])
def image_pull():
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        image = request.json.get('image')
        if not image: return jsonify({"status": "error", "message": "Nazwa obrazu jest wymagana"}), 400
        client.images.pull(image)
        return jsonify({"status": "ok", "message": f"Obraz {image} pobrany"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/image/<image_id>/remove', methods=['POST'])
def image_remove(image_id):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        client.images.remove(image_id, force=True)
        return jsonify({"status": "ok", "message": "Obraz usunięty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/network/create', methods=['POST'])
def network_create():
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        data = request.json
        name = data.get('name')
        if not name: return jsonify({"status": "error", "message": "Nazwa sieci jest wymagana"}), 400
        client.networks.create(name=name, driver=data.get('driver', 'bridge'))
        return jsonify({"status": "ok", "message": f"Sieć {name} utworzona"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/network/<network_id>/remove', methods=['POST'])
def network_remove(network_id):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        network = client.networks.get(network_id)
        name = network.name
        network.remove()
        return jsonify({"status": "ok", "message": f"Sieć {name} usunięta"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/volume/create', methods=['POST'])
def volume_create():
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        name = request.json.get('name')
        if not name: return jsonify({"status": "error", "message": "Nazwa volume jest wymagana"}), 400
        client.volumes.create(name=name)
        return jsonify({"status": "ok", "message": f"Volume {name} utworzony"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/volume/<volume_name>/remove', methods=['POST'])
def volume_remove(volume_name):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        volume = client.volumes.get(volume_name)
        volume.remove()
        return jsonify({"status": "ok", "message": f"Volume {volume_name} usunięty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/stack/create', methods=['POST'])
def stack_create():
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        data = request.json
        name = data.get('name')
        compose_content = data.get('compose')
        if not name or not compose_content:
            return jsonify({"status": "error", "message": "Nazwa i konfiguracja są wymagane"}), 400

        try: yaml.safe_load(compose_content)
        except yaml.YAMLError as e:
            return jsonify({"status": "error", "message": f"Nieprawidłowy YAML: {e}"}), 400

        stack_dir = os.path.join(STACKS_PATH, name)
        os.makedirs(stack_dir, exist_ok=True)
        compose_file = os.path.join(stack_dir, 'docker-compose.yml')
        with open(compose_file, 'w') as f:
            f.write(compose_content)

        result = subprocess.run(['docker', 'compose', '-p', name, '-f', compose_file, 'up', '-d'],
                                capture_output=True, text=True)
        if result.returncode != 0:
            return jsonify({"status": "error", "message": result.stderr}), 500
        return jsonify({"status": "ok", "message": f"Stack {name} uruchomiony"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/stack/<name>/start', methods=['POST'])
def stack_start(name):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        containers = client.containers.list(all=True, filters={'label': f'com.docker.compose.project={name}'})
        for c in containers: c.start()
        return jsonify({"status": "ok", "message": f"Stack {name} uruchomiony"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/stack/<name>/stop', methods=['POST'])
def stack_stop(name):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        containers = client.containers.list(filters={'label': f'com.docker.compose.project={name}'})
        for c in containers: c.stop()
        return jsonify({"status": "ok", "message": f"Stack {name} zatrzymany"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/stack/<name>/restart', methods=['POST'])
def stack_restart(name):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        containers = client.containers.list(filters={'label': f'com.docker.compose.project={name}'})
        for c in containers: c.restart()
        return jsonify({"status": "ok", "message": f"Stack {name} zrestartowany"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/stack/<name>/remove', methods=['POST'])
def stack_remove(name):
    if 'user' not in session: return jsonify({"error": "unauthorized"}), 401
    try:
        stack_dir = os.path.join(STACKS_PATH, name)
        compose_file = os.path.join(stack_dir, 'docker-compose.yml')
        if os.path.exists(compose_file):
            subprocess.run(['docker', 'compose', '-p', name, '-f', compose_file, 'down', '-v'],
                           capture_output=True, text=True)
            os.remove(compose_file)
            try: os.rmdir(stack_dir)
            except: pass
        else:
            containers = client.containers.list(all=True, filters={'label': f'com.docker.compose.project={name}'})
            for c in containers: c.remove(force=True)
        return jsonify({"status": "ok", "message": f"Stack {name} usunięty"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
