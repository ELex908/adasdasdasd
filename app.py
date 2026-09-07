import json
import os
import uuid

from flask import Flask, jsonify, request, send_file, session, redirect
from werkzeug.security import check_password_hash, generate_password_hash

IS_VERCEL = os.environ.get('VERCEL') == '1'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = '/tmp' if IS_VERCEL else BASE_DIR
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
CONVERSIONS_FILE = os.path.join(DATA_DIR, 'conversions.json')
UPLOADS_DIR = os.path.join(DATA_DIR, 'uploads')
DEV_EMAIL = 'michaelyoda210@gmail.com'
DEV_PASSWORD = os.environ.get('DEV_PASSWORD', 'devpass123')

os.makedirs(UPLOADS_DIR, exist_ok=True)

app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-key-in-production')


def seed_dev_user():
    users = load_json(USERS_FILE, [])
    if not any(u['email'] == DEV_EMAIL for u in users):
        users.append({
            'name': 'Enzo Dev',
            'email': DEV_EMAIL,
            'password': generate_password_hash(DEV_PASSWORD),
        })
        save_json(USERS_FILE, users)
        print('Seeded dev account:', DEV_EMAIL, '/', DEV_PASSWORD)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def current_user():
    return session.get('user')


def is_dev():
    user = current_user()
    return user and user.get('email', '').lower() == DEV_EMAIL


def auth():
    return current_user() is not None


# ---------------------------------------------------------------------------
# Static pages
@app.route('/')
def index():
    return send_file(os.path.join(BASE_DIR, 'index.html'))


@app.route('/dashboard')
def dashboard():
    return send_file(os.path.join(BASE_DIR, 'dashboard.html'))


@app.route('/dev')
def dev():
    return send_file(os.path.join(BASE_DIR, 'dev.html'))


# ---------------------------------------------------------------------------
# Auth
@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not name or not email or not password:
        return jsonify({'error': 'Please fill in all fields.'}), 400
    if '@' not in email:
        return jsonify({'error': 'Please enter a valid email.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters.'}), 400

    users = load_json(USERS_FILE, [])
    if any(u['email'] == email for u in users):
        return jsonify({'error': 'An account with that email already exists.'}), 400

    users.append({
        'name': name,
        'email': email,
        'password': generate_password_hash(password),
    })
    save_json(USERS_FILE, users)
    return jsonify({'ok': True})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Please enter your email and password.'}), 400

    users = load_json(USERS_FILE, [])
    user = next((u for u in users if u['email'] == email), None)

    if email == DEV_EMAIL and not user:
        if password != DEV_PASSWORD:
            return jsonify({'error': 'Wrong email or password.'}), 400
        session['user'] = {'name': 'Enzo Dev', 'email': DEV_EMAIL}
        return jsonify({'ok': True, 'user': {'name': 'Enzo Dev', 'email': DEV_EMAIL}})

    if not user or not check_password_hash(user['password'], password):
        return jsonify({'error': 'Wrong email or password.'}), 400

    session['user'] = {'name': user['name'], 'email': user['email']}
    return jsonify({'ok': True, 'user': {'name': user['name'], 'email': user['email']}})


@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({'ok': True})


@app.route('/api/me')
def me():
    user = current_user()
    if not user:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'user': user, 'is_dev': is_dev()})


# ---------------------------------------------------------------------------
# Dev panel (only for michaelyoda210@gmail.com)
@app.route('/api/conversions', methods=['GET'])
def get_conversions():
    if not is_dev():
        return jsonify({'error': 'Forbidden'}), 403
    return jsonify(load_json(CONVERSIONS_FILE, []))


@app.route('/api/conversions', methods=['POST'])
def add_conversion():
    if not auth():
        return jsonify({'error': 'Not logged in'}), 401

    data = request.get_json(silent=True) or {}
    user = current_user()
    conversions = load_json(CONVERSIONS_FILE, [])

    conversions.insert(0, {
        'id': str(uuid.uuid4()),
        'name': user['name'],
        'initials': ''.join(p[0] for p in user['name'].split() if p)[:2].upper() or '?',
        'email': user['email'],
        'file': data.get('file', 'figma.json'),
        'data': data.get('data', '{}'),
        'time': (data.get('time') or ''),
        'status': 'queued',
    })
    save_json(CONVERSIONS_FILE, conversions)
    return jsonify({'ok': True}), 201


@app.route('/api/conversions/<conv_id>/sendback', methods=['POST'])
def send_back(conv_id):
    if not is_dev():
        return jsonify({'error': 'Forbidden'}), 403

    conversions = load_json(CONVERSIONS_FILE, [])
    for conv in conversions:
        if conv.get('id') == conv_id:
            uploaded = request.files.get('file')
            if uploaded and uploaded.filename:
                zip_path = os.path.join(UPLOADS_DIR, conv_id + '.zip')
                uploaded.save(zip_path)
                conv['zip_name'] = uploaded.filename
            conv['status'] = 'sent'
            save_json(CONVERSIONS_FILE, conversions)
            return jsonify({'ok': True})
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/conversions/<conv_id>/delivery')
def conversion_delivery(conv_id):
    if not is_dev():
        return jsonify({'error': 'Forbidden'}), 403

    conversions = load_json(CONVERSIONS_FILE, [])
    conv = next((c for c in conversions if c.get('id') == conv_id), None)
    zip_path = os.path.join(UPLOADS_DIR, conv_id + '.zip')
    if not conv or not os.path.exists(zip_path):
        return jsonify({'error': 'Not found'}), 404
    return send_file(zip_path, as_attachment=True,
                     download_name=conv.get('zip_name') or 'delivery.zip')


@app.route('/api/my-conversions')
def my_conversions():
    if not auth():
        return jsonify({'error': 'Not logged in'}), 401

    email = current_user()['email']
    conversions = load_json(CONVERSIONS_FILE, [])
    mine = [{
        'id': c.get('id'),
        'file': c.get('file'),
        'status': c.get('status'),
        'zip_name': c.get('zip_name'),
    } for c in conversions if c.get('email') == email]
    return jsonify(mine)


@app.route('/api/conversions/<conv_id>/my-delivery')
def my_delivery(conv_id):
    if not auth():
        return jsonify({'error': 'Not logged in'}), 401

    conversions = load_json(CONVERSIONS_FILE, [])
    conv = next((c for c in conversions if c.get('id') == conv_id), None)
    if not conv or conv.get('email') != current_user()['email']:
        return jsonify({'error': 'Not found'}), 404
    zip_path = os.path.join(UPLOADS_DIR, conv_id + '.zip')
    if not os.path.exists(zip_path):
        return jsonify({'error': 'Not found'}), 404
    return send_file(zip_path, as_attachment=True,
                     download_name=conv.get('zip_name') or 'delivery.zip')


@app.route('/api/conversions/<conv_id>/download')
def download_conversion(conv_id):
    if not is_dev():
        return jsonify({'error': 'Forbidden'}), 403

    conversions = load_json(CONVERSIONS_FILE, [])
    conv = next((c for c in conversions if c.get('id') == conv_id), None)
    if not conv:
        return jsonify({'error': 'Not found'}), 404

    tmp = os.path.join(DATA_DIR, 'download_' + conv_id + '.json')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(conv.get('data', '{}'))
    response = send_file(tmp, as_attachment=True, download_name=conv.get('file', 'figma.json'))
    response.call_on_close(lambda: os.path.exists(tmp) and os.remove(tmp))
    return response


if __name__ == '__main__':
    seed_dev_user()
    app.run(debug=True, port=5000)