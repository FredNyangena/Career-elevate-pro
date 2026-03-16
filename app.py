import os, base64, requests, uuid
from datetime import datetime
from flask import Flask, render_template_string, redirect, url_for, flash, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv('SECRET_KEY', 'dev-secret-123'),
    SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///career_pro.db').replace("postgres://", "postgresql://", 1),
    SQLALCHEMY_TRACK_MODIFICATIONS=False
)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- DATABASE MODELS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(20))
    password = db.Column(db.String(200))
    role = db.Column(db.String(20), default='user')
    transactions = db.relationship('Transaction', backref='customer', lazy=True)

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    price = db.Column(db.Float)
    description = db.Column(db.Text)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    checkout_id = db.Column(db.String(100), unique=True)
    amount = db.Column(db.Float)
    status = db.Column(db.String(20), default='Pending')
    receipt = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- MPESA HELPERS ---
def get_mpesa_token():
    try:
        auth = (os.getenv('MPESA_CONSUMER_KEY'), os.getenv('MPESA_CONSUMER_SECRET'))
        r = requests.get("https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials", auth=auth)
        return r.json().get('access_token')
    except: return None

# --- ROUTES ---
@app.route('/')
def index():
    services = Service.query.all()
    return render_template_string(LAYOUT_HTML, content=INDEX_CONTENT, services=services)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid login details', 'danger')
    return render_template_string(LAYOUT_HTML, content=LOGIN_CONTENT)

@app.route('/pay/<int:service_id>', methods=['POST'])
@login_required
def pay(service_id):
    service = Service.query.get(service_id)
    token = get_mpesa_token()
    if not token:
        flash("M-Pesa API Error. Check your Credentials.", "danger")
        return redirect(url_for('index'))
        
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(f"{os.getenv('MPESA_SHORTCODE')}{os.getenv('MPESA_PASSKEY')}{timestamp}".encode()).decode()
    
    payload = {
        "BusinessShortCode": os.getenv('MPESA_SHORTCODE'),
        "Password": password, "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline", "Amount": int(service.price),
        "PartyA": request.form.get('phone'), "PartyB": os.getenv('MPESA_SHORTCODE'),
        "PhoneNumber": request.form.get('phone'), "CallBackURL": os.getenv('MPESA_CALLBACK_URL'),
        "AccountReference": service.title[:12], "TransactionDesc": "Payment"
    }
    res = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest", 
                       json=payload, headers={"Authorization": f"Bearer {token}"}).json()
    
    if res.get('ResponseCode') == '0':
        db.session.add(Transaction(checkout_id=res['CheckoutRequestID'], amount=service.price, user_id=current_user.id, service_id=service.id))
        db.session.commit()
        flash("STK Push Sent! Check your phone.", "success")
    return redirect(url_for('index'))

@app.cli.command("init-db")
def init_db():
    db.create_all()
    if not User.query.filter_by(email='admin@example.com').first():
        db.session.add(User(name="Admin User", email="admin@example.com", phone="254700000000", 
                           password=generate_password_hash("admin123"), role='admin'))
    services = [
        ("Consultation", 1000), ("CV Revamp", 2000), 
        ("LinkedIn Pro", 6000), ("Career Coaching", 6000), ("Interview Prep", 3000)
    ]
    for t, p in services:
        if not Service.query.filter_by(title=t).first():
            db.session.add(Service(title=t, price=p, description="Premium Kenyan Career Service"))
    db.session.commit()
    print("Database Initialized!")

# --- UI TEMPLATES ---
LAYOUT_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <title>CareerElevate Pro</title>
</head>
<body class="bg-light">
    <nav class="navbar navbar-dark bg-dark mb-4">
        <div class="container">
            <a class="navbar-brand fw-bold" href="/">CareerElevate <span class="text-success">Pro</span></a>
            <div>
                {% if current_user.is_authenticated %}
                <span class="text-white me-3">Hi, {{current_user.name}}</span>
                <a href="/logout" class="btn btn-sm btn-outline-light">Logout</a>
                {% else %}
                <a href="/login" class="btn btn-sm btn-success">Login</a>
                {% endif %}
            </div>
        </div>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% for cat, msg in messages %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}
        {% endwith %}
        {{ content | safe }}
    </div>
</body>
</html>
'''

INDEX_CONTENT = '''
<div class="row">
    {% for s in services %}
    <div class="col-md-4 mb-4">
        <div class="card shadow-sm">
            <div class="card-body">
                <h4>{{s.title}}</h4>
                <p class="text-muted small">Professional career advancement service.</p>
                <h3 class="text-success">KES {{s.price}}</h3>
                <form action="/pay/{{s.id}}" method="POST">
                    <input type="text" name="phone" class="form-control mb-2" placeholder="2547XXXXXXXX" required>
                    <button class="btn btn-primary w-100">Pay with M-Pesa</button>
                </form>
            </div>
        </div>
    </div>
    {% endfor %}
</div>
'''

LOGIN_CONTENT = '''
<div class="row justify-content-center"><div class="col-md-4 card p-4 shadow">
    <form method="POST"><h3>Login</h3>
    <input name="email" class="form-control mb-2" placeholder="Email" required>
    <input name="password" type="password" class="form-control mb-3" placeholder="Password" required>
    <button class="btn btn-success w-100">Login</button></form>
</div></div>
'''

if __name__ == '__main__':
    app.run(debug=True)
