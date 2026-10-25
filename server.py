from flask import Flask, request, jsonify, session, redirect, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import os, json, uuid, random, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests

load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv('SECRET_KEY', 'change-me-secret-key-12345')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5000')

# ---------- Настройки почты ----------
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.yandex.ru')
SMTP_PORT = int(os.getenv('SMTP_PORT', '465'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASS', '')

# ---------- OAuth ----------
YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID', '')
YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET', '')
YANDEX_REDIRECT_URI = os.getenv('YANDEX_REDIRECT_URI', f'{FRONTEND_URL}/auth/yandex/callback')

VK_CLIENT_ID = os.getenv('VK_CLIENT_ID', '')
VK_CLIENT_SECRET = os.getenv('VK_CLIENT_SECRET', '')
VK_REDIRECT_URI = os.getenv('VK_REDIRECT_URI', f'{FRONTEND_URL}/auth/vk/callback')

CORS(app, supports_credentials=True, origins=[FRONTEND_URL])

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

def send_email(to, subject, body_text, body_html=None):
    if not SMTP_USER or not SMTP_PASS:
        print(f'\n=== EMAIL (DEMO) to {to} ===\n{subject}: {body_text}\n================\n')
        return True
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = SMTP_USER
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body_text, 'plain'))
        if body_html:
            msg.attach(MIMEText(body_html, 'html'))
        context = ssl.create_default_context()
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.starttls(context=context)
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f'Email error: {e}')
        return False

def new_user(name, email, password=None, provider='email', photo=''):
    return {
        'id': str(uuid.uuid4()),
        'name': name,
        'email': email,
        'password': generate_password_hash(password) if password else None,
        'provider': provider,
        'photo': photo,
        'photos': [],
        'nameA': '', 'age': '', 'bio': '',
        'course': '4', 'groupLetter': '', 'groupNumber': '',
        'specialty': '', 'specialtyCode': '', 'specialtyCustom': '',
        'individual': None, 'quotes': [], 'competitions': [], 'petitions': [],
        'sched': {'file': '', 'fileName': '', 'text': '', 'time': '16:00', 'enabled': False}
    }

def get_safe_user(u):
    return {k: v for k, v in u.items() if k != 'password'}

# ---------- Маршруты ----------
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/register', methods=['POST'])
def register():
    d = request.json or {}
    email = d.get('email', '').strip().lower()
    name = d.get('name', '').strip()
    pwd = d.get('password', '')
    code = d.get('code', '')
    phone = d.get('phone', '')

    if not email or not name or not pwd:
        return jsonify({'error': 'Заполни все поля'}), 400
    if len(pwd) < 6:
        return jsonify({'error': 'Пароль короче 6 символов'}), 400
    if email in users:
        return jsonify({'error': 'Такой email уже есть'}), 400
    if code:
        st = codes.get(email)
        if not st or st['code'] != code or datetime.now() > datetime.fromisoformat(st['exp']):
            return jsonify({'error': 'Неверный или устаревший код'}), 400

    u = new_user(name, email, pwd, provider='email')
    u['phone'] = phone
    users[email] = u
    save_json(USERS_FILE, users)
    session['user_email'] = email
    return jsonify({'ok': True, 'user': get_safe_user(u)})

@app.route('/api/login', methods=['POST'])
def login():
    d = request.json or {}
    email = d.get('email', '').strip().lower()
    pwd = d.get('password', '')
    if email not in users or not check_password_hash(users[email]['password'], pwd):
        return jsonify({'error': 'Неверный email или пароль'}), 401
    session['user_email'] = email
    return jsonify({'ok': True, 'user': get_safe_user(users[email])})

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

    subject = 'Код подтверждения для портфолио СКОиПТ'
    body = f'Ваш код подтверждения: {code}\nДействует 10 минут.'
    html = f'<p>Ваш код подтверждения: <b>{code}</b></p><p>Действует 10 минут.</p>'

    sent = False
    if email:
        sent = send_email(email, subject, body, html)
    elif phone:
        print(f'\n=== SMS (DEMO) to {phone} ===\nКод: {code}\n================\n')
        sent = True

    return jsonify({'ok': True, 'demo_code': code if not SMTP_USER else None})

@app.route('/api/user')
def me():
    email = session.get('user_email')
    if not email or email not in users:
        return jsonify({'error': 'Not logged in'}), 401
    return jsonify({'user': get_safe_user(users[email])})

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

@app.route('/api/delete-account', methods=['POST', 'DELETE'])
def delete_account():
    email = session.get('user_email')
    if not email or email not in users:
        return jsonify({'error': 'Not logged in'}), 401
    d = request.json or {}
    pwd = d.get('password', '')
    if pwd and not check_password_hash(users[email]['password'], pwd):
        return jsonify({'error': 'Неверный пароль'}), 401
    del users[email]
    save_json(USERS_FILE, users)
    session.pop('user_email', None)
    return jsonify({'ok': True})

@app.route('/api/logout')
def logout():
    session.pop('user_email', None)
    return jsonify({'ok': True})

# ---------- YANDEX OAUTH ----------
@app.route('/auth/yandex')
def auth_yandex():
    if not YANDEX_CLIENT_ID:
        return jsonify({'error': 'Yandex OAuth not configured'}), 501
    state = str(uuid.uuid4())
    session['oauth_state'] = state
    session['oauth_provider'] = 'yandex'
    params = {
        'response_type': 'code',
        'client_id': YANDEX_CLIENT_ID,
        'redirect_uri': YANDEX_REDIRECT_URI,
        'scope': 'login:email login:info',
        'state': state
    }
    return redirect('https://oauth.yandex.ru/authorize?' + requests.compat.urlencode(params))

@app.route('/auth/yandex/callback')
def auth_yandex_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    if error:
        return redirect(f'{FRONTEND_URL}/#auth?error={error}')
    if state != session.get('oauth_state'):
        return jsonify({'error': 'Invalid state'}), 400

    token_data = {
        'code': code,
        'client_id': YANDEX_CLIENT_ID,
        'client_secret': YANDEX_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'redirect_uri': YANDEX_REDIRECT_URI
    }
    token_resp = requests.post('https://oauth.yandex.ru/token', data=token_data)
    token_json = token_resp.json()
    access_token = token_json.get('access_token')

    if not access_token:
        return jsonify({'error': 'Token error', 'details': token_json}), 400

    user_resp = requests.get('https://login.yandex.ru/info', headers={'Authorization': f'OAuth {access_token}'})
    user_info = user_resp.json()

    email = user_info.get('email')
    name = user_info.get('display_name') or user_info.get('real_name') or 'Пользователь Яндекс'
    photo = user_info.get('avatar')

    if not email:
        email = f"yandex_{user_info.get('id', 'unknown')}@yandex.invalid"

    users = load_json(USERS_FILE, {})
    if email not in users:
        users[email] = new_user(name, email, provider='yandex', photo=photo)
        save_json(USERS_FILE, users)

    session['user_email'] = email
    return redirect(f'{FRONTEND_URL}/#photos?auth=success')

# ---------- VK OAUTH ----------
@app.route('/auth/vk')
def auth_vk():
    if not VK_CLIENT_ID:
        return jsonify({'error': 'VK OAuth not configured'}), 501
    state = str(uuid.uuid4())
    session['oauth_state'] = state
    session['oauth_provider'] = 'vk'
    params = {
        'client_id': VK_CLIENT_ID,
        'redirect_uri': VK_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'email',
        'state': state,
        'v': '5.199'
    }
    return redirect('https://oauth.vk.com/authorize?' + requests.compat.urlencode(params))

@app.route('/auth/vk/callback')
def auth_vk_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    if error:
        return redirect(f'{FRONTEND_URL}/#auth?error={error}')
    if state != session.get('oauth_state'):
        return jsonify({'error': 'Invalid state'}), 400

    token_data = {
        'client_id': VK_CLIENT_ID,
        'client_secret': VK_CLIENT_SECRET,
        'code': code,
        'redirect_uri': VK_REDIRECT_URI,
        'grant_type': 'authorization_code',
        'v': '5.199'
    }
    token_resp = requests.get('https://oauth.vk.com/access_token', params=token_data)
    token_json = token_resp.json()
    access_token = token_json.get('access_token')
    user_id_vk = token_json.get('user_id')

    if not access_token:
        return jsonify({'error': 'Token error', 'details': token_json}), 400

    user_resp = requests.get('https://api.vk.com/method/users.get', params={
        'user_ids': user_id_vk,
        'fields': 'photo_200,email',
        'access_token': access_token,
        'v': '5.199'
    })
    user_info = user_resp.json().get('response', [{}])[0]

    name = (user_info.get('first_name', '') + ' ' + user_info.get('last_name', '')).strip() or 'Пользователь VK'
    photo = user_info.get('photo_200', '')
    email = user_info.get('email', f"vk_{user_id_vk}@vk.invalid")

    users = load_json(USERS_FILE, {})
    if email not in users:
        users[email] = new_user(name, email, provider='vk', photo=photo)
        save_json(USERS_FILE, users)

    session['user_email'] = email
    return redirect(f'{FRONTEND_URL}/#photos?auth=success')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))