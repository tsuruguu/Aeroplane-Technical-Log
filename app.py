"""
Główny plik startowy aplikacji (Application Factory).

Zawiera funkcję `create_app`, która:
1. Konfiguruje aplikację Flask.
2. Inicjalizuje połączenie z bazą danych.
3. Konfiguruje zabezpieczenia (CSRF, Limiter, Secure Cookies).
4. Rejestruje Blueprints (moduły routingu).
"""

from flask import Flask
from dotenv import load_dotenv
import os

# Import instancji z extensions.py
from extensions import db, login_manager, csrf, limiter

from models import Uzytkownik
from routes.auth import auth_bp
from routes.flights import flights_bp
from routes.reports import reports_bp
from routes.mechanic import mechanic_bp
from routes.admin import admin_bp

load_dotenv()

def create_app():
    """
    Implementacja wzorca Application Factory dla frameworka Flask.

    Konfiguracja stosu technologicznego:
    - Inicjalizacja rozszerzeń (ORM, Security, Rate Limiter).
    - Konfiguracja middleware bezpieczeństwa: CSRF Protection, Secure Cookie,
      HSTS (w trybie produkcyjnym).
    - Rejestracja modułów routingu (Blueprints).

    Returns:
        Flask: Skonfigurowana aplikacja gotowa do uruchomienia.
    """
    app = Flask(__name__)

    # Konfiguracja podstawowa
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Bezpieczeństwo Ciasteczek
    # W produkcji wymuszamy HTTPS i HttpOnly
    is_production = os.getenv('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['SESSION_COOKIE_HTTPONLY'] = True

    # Debug Mode
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.config['DEBUG'] = debug_mode

    # Konfiguracja Uploadów
    UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    # --- INICJALIZACJA ROZSZERZEŃ ---
    db.init_app(app)
    csrf.init_app(app)

    # Konfiguracja limitera
    limiter.storage_uri = "memory://"
    limiter.default_limits = ["200 per day", "50 per hour"]
    limiter.init_app(app)

    # Konfiguracja logowania
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Musisz się zalogować, aby zobaczyć Dziennik Techniczny!'
    login_manager.login_message_category = 'warning'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return Uzytkownik.query.get(int(user_id))

    # Rejestracja Modułów (Blueprints)
    app.register_blueprint(auth_bp)
    app.register_blueprint(flights_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(mechanic_bp)
    app.register_blueprint(admin_bp)

    @app.route('/')
    def index():
        from flask import render_template
        return render_template('index.html')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run()