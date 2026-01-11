"""
Inicjalizacja rozszerzeń Flask.

Plik ten służy do rozwiązania problemu cyklicznych importów.
Tutaj tworzone są instancje rozszerzeń (DB, Login, CSRF, Limiter),
które następnie są konfigurowane w `app.py` i importowane w modelach/trasach.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

#: Główny obiekt bazy danych SQLAlchemy
db = SQLAlchemy()

#: Obiekt zarządzający sesją użytkownika
login_manager = LoginManager()

#: Ochrona przed atakami CSRF (Cross-Site Request Forgery)
csrf = CSRFProtect()

#: Ochrona przed atakami Brute-Force (Limitowanie zapytań)
limiter = Limiter(key_func=get_remote_address)