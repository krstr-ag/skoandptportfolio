from flask import Flask, request, jsonify, session, redirect, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import os, json, uuid, random
from datetime import datetime, timedelta

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv('SECRET_KEY', 'change-me-secret-key-12345')
CORS(app, supports_credentials=True, origins=[os.getenv('FRONTEND_URL', '*')])

USERS_FILE = 'users.json'
CODES_FILE = 'codes.json'

def load_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

users = load_json(USERS_FILE, {})
codes = load_json(CODES_FILE, {})

def gen_code():
    return str(random.randint(100000, 999999))

# ---------- Сервер отдаёт сам сайт ----------
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# ---------- Регистрация ----------
@app.route('/api/register', methods=['POST'])
def register():
    d = request.json or {}
    email = d.get('email', '').strip().lower()
    name = d.get('name', '').strip()
    pwd = d.get('password', '')
    code = d.get('code', '')
    
    if not email or not name or not pwd:
        return jsonify({'error': 'Заполни все поля'}), 400
    if len(pwd) < 6:
        return jsonify({'error': 'Пароль короче 6 символов'}), 400
    if email in users:
        return jsonify({'error': 'Такой email уже есть'}), 400
    if code:
        st = codes.get(email)
        if not st or st['code'] != code or datetime.now() > datetime.fromisoformat(st['exp']):
            return jsonify({'error': 'Неверный код'}), 400
    
    u = {
        'id': str(uuid.uuid4()),
        'name': name,
        'email': email,
        'password': generate_password_hash(pwd),
        'provider': 'email',
        'photo': '', 'photos': [],
        'nameA': '', 'age': '', 'bio': '',
        'course': '4', 'groupLetter': '', 'groupNumber': '',
        'specialty': '', 'specialtyCode': '', 'specialtyCustom': '',
        'individual': None, 'quotes': [], 'competitions': [], 'petitions': [],
        'sched': {'file': '', 'fileName': '', 'text': '', 'time': '16:00', 'enabled': False}
    }
    users[email] = u
    save_json(USERS_FILE, users)
    session['user_email'] = email
    safe = {k: v for k, v in u.items() if k != 'password'}
    return jsonify({'ok': True, 'user': safe})

# ---------- Вход ----------
@app.route('/api/login', methods=['POST'])
def login():
    d = request.json or {}
    email = d.get('email', '').strip().lower()
    pwd = d.get('password', '')
    if email not in users or not check_password_hash(users[email]['password'], pwd):
        return jsonify({'error': 'Неверный email или пароль'}), 401
    session['user_email'] = email
    safe = {k: v for k, v in users[email].items() if k != 'password'}
    return jsonify({'ok': True, 'user': safe})

# ---------- Код подтверждения ----------
@app.route('/api/send-code', methods=['POST'])
def send_code():
    d = request.json or {}
    email = d.get('email', '').strip().lower()
    phone = d.get('phone', '').strip()
    target = email or phone
    if not target:
        return jsonify({'error': 'Укажи email или телефон'}), 400
    
    code = gen_code()
    codes[target] = {'code': code, 'exp': (datetime.now() + timedelta(minutes=10)).isoformat()}
    save_json(CODES_FILE, codes)
    
    print(f'\n=== КОД ПОДТВЕРЖДЕНИЯ для {target} ===\nКод: {code}\n=================================\n')
    return jsonify({'ok': True, 'demo_code': code})

@app.route('/api/user')
def me():
    email = session.get('user_email')
    if not email or email not in users:
        return jsonify({'error': 'Not logged in'}), 401
    u = users[email]
    return jsonify({'user': {k: v for k, v in u.items() if k != 'password'}})

@app.route('/api/save', methods=['POST'])
def save():
    email = session.get('user_email')
    if not email or email not in users:
        return jsonify({'error': 'Not logged in'}), 401
    d = request.json or {}
    for k, v in d.items():
        if k != 'password':
            users[email][k] = v
    save_json(USERS_FILE, users)
    return jsonify({'ok': True})

@app.route('/api/logout')
def logout():
    session.pop('user_email', None)
    return jsonify({'ok': True})

# ---------- Соцсети (демо) ----------
@app.route('/auth/<provider>')
def oauth(provider):
    return jsonify({'error': f'Нужно настроить {provider} OAuth в консоли сервера'}), 501

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))