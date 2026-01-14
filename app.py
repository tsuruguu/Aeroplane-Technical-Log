"""
Główny plik startowy aplikacji (Application Factory).

Zawiera funkcję `create_app`, która:
1. Konfiguruje aplikację Flask.
2. Inicjalizuje połączenie z bazą danych.
3. Konfiguruje zabezpieczenia (CSRF, Limiter, Secure Cookies, Cryptographic Auditing).
4. Rejestruje Blueprints (moduły routingu).
"""

from flask import Flask, render_template, request
from dotenv import load_dotenv
import os

from extensions import db, login_manager, csrf, limiter

from models import Uzytkownik
from routes.auth import auth_bp
from routes.flights import flights_bp
from routes.reports import reports_bp
from routes.mechanic import mechanic_bp
from routes.admin import admin_bp

from logger_config import setup_logging
import logging

setup_logging()
load_dotenv()

def create_app():
    """
    Implementacja wzorca Application Factory dla frameworka Flask.

    Konfiguracja stosu technologicznego:
    - Inicjalizacja rozszerzeń (ORM, Security, Rate Limiter).
    - Konfiguracja middleware bezpieczeństwa: CSRF Protection, Secure Cookie,
      HSTS (w trybie produkcyjnym).
    - Rejestracja modułów routingu (Blueprints),
    - Konfiguracja globalnych handlerów błędów (Audit Trails).

    Returns:
        Flask: Skonfigurowana aplikacja gotowa do uruchomienia.
    """
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    uri = os.getenv('DATABASE_URL')
    if uri and uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    is_production = os.getenv('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['SESSION_COOKIE_HTTPONLY'] = True



    # Debug Mode
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.config['DEBUG'] = debug_mode



    UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    db.init_app(app)
    csrf.init_app(app)

    limiter.storage_uri = "memory://"
    limiter.default_limits = ["200 per day", "50 per hour"]
    limiter.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Musisz się zalogować, aby zobaczyć Dziennik Techniczny!'
    login_manager.login_message_category = 'warning'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        """Ładowanie użytkownika dla Flask-Login."""
        return Uzytkownik.query.get(int(user_id))

    app.register_blueprint(auth_bp)
    app.register_blueprint(flights_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(mechanic_bp)
    app.register_blueprint(admin_bp)

    @app.route('/')
    def index():
        """Strona powitalna."""
        return render_template('index.html')

    logging.getLogger("application").info("APP_STARTUP", extra={
        'event': 'SYSTEM_BOOT',
        'env': os.getenv('FLASK_ENV', 'development'),
        'debug_mode': app.config['DEBUG']
    })

    @app.errorhandler(404)
    def page_not_found(e):
        """Audyt 404: Wykrywanie prób skanowania zasobów (Reconnaissance)."""
        logging.getLogger("security").warning("PAGE_NOT_FOUND", extra={
            'event': 'RECONNAISSANCE',
            'url': request.url,
            'src_ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent')
        })
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        """Audyt 500: Rejestrowanie awarii krytycznych systemu."""
        logging.getLogger("error").critical("INTERNAL_SERVER_ERROR", exc_info=True, extra={
            'event': 'SYSTEM_FAILURE',
            'url': request.url,
            'src_ip': request.remote_addr
        })
        return render_template('500.html'), 500

    return app



if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000)