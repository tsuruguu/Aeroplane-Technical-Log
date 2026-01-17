"""
Moduł uwierzytelniania (Authentication) z systemem Audit Trail.

Obsługuje logowanie, wylogowywanie, rejestrację nowych użytkowników
oraz zarządzanie profilem.

**System Logowania i Audytu (Cybersecurity Compliance)**
Wszystkie zdarzenia w tym module są logowane do kanału `security` w formacie JSON
z cyfrowym podpisem HMAC-SHA256, co zapewnia integralność logów (nienaruszalność).

Przykład logu bezpieczeństwa (JSON):
{
    "timestamp": "2026-01-11T18:20:01.123Z",
    "level": "WARNING",
    "event": "AUTH_FAILURE",
    "user_attempted": "admin",
    "src_ip": "192.168.1.15",
    "message": "Błędna próba logowania: nieprawidłowe hasło",
    "signature": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
"""
import secrets
import string
import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import limiter
from models import Uzytkownik
# from database import db
from extensions import db
from sqlalchemy import text
import re

auth_bp = Blueprint('auth', __name__)
security_logger = logging.getLogger("security")
app_logger = logging.getLogger("application")

@auth_bp.route('/login', methods=['GET','POST'])
@limiter.limit("5 per minute")
def login():
    """
        Proces uwierzytelniania z wielowarstwowym mechanizmem obronnym.

        **Warstwy bezpieczeństwa**
        1. Rate Limiting: Ograniczenie prób logowania na poziomie IP (Flask-Limiter)
           w celu mitigacji ataków Brute-force i Dictionary.
        2. Kryptografia: Weryfikacja hasła funkcją `check_password_hash` z solą
           (odporność na Rainbow Tables).
        3. Stan konta: Weryfikacja logiczna flagi `deleted_at` w profilu pilota
           (tzw. Administrative Lockout).
        4. Session Management: Inicjalizacja bezpiecznej sesji (HttpOnly, Secure flag).

        **Przepływ Logiki**
        - Pobranie użytkownika na podstawie unikalnego loginu.
        - Weryfikacja kryptograficzna hasła.
        - Sprawdzenie flagi aktywności konta (blokada administracyjna).
        - Inicjalizacja sesji użytkownika (Flask-Login).

        Returns:
            Response: Przekierowanie do strony głównej (sukces - 200) lub ponowne wyświetlenie formularza (błąd - 302).
    """
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        login_input = request.form.get('login')
        haslo_input = request.form.get('password')
        src_ip = request.remote_addr
        user = Uzytkownik.query.filter_by(login=login_input).first()

        if user and check_password_hash(user.haslo_hash, haslo_input):
            if user.id_pilot:
                is_deleted = db.session.execute(
                    text("SELECT deleted_at FROM pdt_core.pilot WHERE id_pilot = :id"),
                    {'id': user.id_pilot}
                ).scalar()

                if is_deleted is not None:
                    security_logger.warning("ACCOUNT_LOCKED_ATTEMPT", extra={
                        'event': 'AUTH_LOCKOUT',
                        'user': login_input,
                        'src_ip': src_ip,
                        'details': 'Próba logowania na konto zablokowane administracyjnie'
                    })
                    flash('To konto zostało zablokowane przez administratora.', 'danger')
                    return render_template('login.html')

            login_user(user)
            security_logger.info("USER_LOGIN_SUCCESS", extra={
                'event': 'AUTH_SUCCESS',
                'user': user.login,
                'role': user.rola,
                'src_ip': src_ip,
                'details': 'Użytkownik zalogowany pomyślnie'
            })
            flash('Zalogowano pomyślnie!', 'success')
            return redirect(url_for('index'))
        else:
            security_logger.warning("USER_LOGIN_FAILURE", extra={
                'event': 'AUTH_FAILURE',
                'user_attempted': login_input,
                'src_ip': src_ip,
                'details': 'Nieudana próba logowania: błędne poświadczenia'
            })
            flash('Błędny login lub hasło.', 'danger')

    return render_template('login.html')



@auth_bp.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    """
        Terminuje sesję użytkownika i unieważnia tokeny dostępowe.

        Bezpiecznie wylogowuje użytkownika poprzez usunięcie identyfikatora sesji
        z ciasteczka przeglądarki (korzystając z `flask_login.logout_user`).
        Zapobiega to atakom typu Session Hijacking (przejęcie aktywnej sesji),
        gdyż po wylogowaniu stary token sesyjny staje się nieważny.

        Returns:
            Response: Przekierowanie do strony logowania.
    """
    user_name = current_user.login
    logout_user()
    security_logger.info("USER_LOGOUT", extra={
        'event': 'AUTH_LOGOUT',
        'user': user_name,
        'src_ip': request.remote_addr,
        'details': 'Użytkownik wylogował się poprawnie'
    })
    flash('Wylogowano pomyślnie.', 'info')
    return redirect(url_for('auth.login'))


def generate_strong_password():
    """
        Kryptograficznie bezpieczny generator haseł (o wysokiej entropii).

        Używany przez Administratora przy tworzeniu nowych kont, aby uniknąć
        nadawania słabych haseł domyślnych (np. "admin123").

        **Implementacja:**
        Korzysta z modułu `secrets` (a nie `random`), co gwarantuje wysoką entropię
        i nieprzewidywalność wygenerowanych znaków. Algorytm w pętli `while` upewnia się,
        że wylosowany ciąg spełnia rygorystyczne zasady polityki haseł (duże litery, znaki specjalne).

        Returns:
            str: Losowe, bezpieczne hasło (min. 12 znaków).
    """
    uppercase = string.ascii_uppercase
    special = "!@#$%^&*(),.?\":{}|<>"
    all_chars = string.ascii_letters + string.digits + special

    while True:
        password = ''.join(secrets.choice(all_chars) for _ in range(14))
        if (len(password) >= 12 and
                len(re.findall(r'[A-Z]', password)) >= 2 and
                len(re.findall(r'[!@#$%^&*(),.?":{}|<>]', password)) >= 2):
            return password

@auth_bp.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    """
        Rejestracja nowego użytkownika w systemie (Procedura Administracyjna).

        Funkcja dostępna tylko dla roli 'admin'. Realizuje **transakcyjne** utworzenie
        tożsamości w systemie, zapewniając spójność danych między różnymi schematami bazy.

        **Transakcyjność (Atomowość):**
        Operacja jest wykonywana w ramach jednej transakcji bazy danych (`db.session`):
        1.  `INSERT` do `pdt_core.pilot` – tworzy profil osobowy.
        2.  `INSERT` do `pdt_auth.uzytkownik` – tworzy dane logowania, linkując je kluczem obcym do pilota.
        Jeśli którykolwiek krok zawiedzie, następuje `ROLLBACK`, zapobiegając powstaniu "sierot" w bazie.

        **Bezpieczeństwo:**
        - Generowanie silnego hasła tymczasowego (wymuszona złożoność: duże litery, znaki specjalne).
        - Haszowanie hasła przed zapisem do bazy.

        Returns:
            Response: Widok rejestracji z komunikatem o wygenerowanym haśle.
    """
    if current_user.rola != 'admin':
        security_logger.critical("UNAUTHORIZED_ACCESS_ATTEMPT", extra={
            'event': 'ACCESS_VIOLATION',
            'user': current_user.login,
            'target': 'register_page',
            'src_ip': request.remote_addr,
            'details': 'Próba dostępu do rejestracji bez uprawnień admina'
        })
        flash('Brak uprawnień!', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        imie = request.form.get('imie')
        nazwisko = request.form.get('nazwisko')
        login_new = request.form.get('login')
        rola = request.form.get('rola')

        temp_password = generate_strong_password()
        hashed_password = generate_password_hash(temp_password)

        try:
            res = db.session.execute(text("""
                                          INSERT INTO pdt_core.pilot (imie, nazwisko)
                                          VALUES (:i, :n)
                                          RETURNING id_pilot
                                          """), {'i': imie, 'n': nazwisko})
            new_pilot_id = res.fetchone()[0]

            db.session.execute(text("""
                                    INSERT INTO pdt_auth.uzytkownik (login, haslo_hash, rola, id_pilot)
                                    VALUES (:login, :password, :rola, :id_pilot)
                                    """), {
                                   'login': login_new, 'password': hashed_password,
                                   'rola': rola, 'id_pilot': new_pilot_id
                               })
            db.session.commit()

            security_logger.info("USER_CREATED", extra={
                'event': 'USER_PROVISIONING',
                'admin_user': current_user.login,
                'new_user': login_new,
                'new_pilot_id': new_pilot_id,
                'src_ip': request.remote_addr,
                'details': f'Administrator utworzył nowe konto dla {imie} {nazwisko}'
            })

            flash(f'Utworzono konto dla {imie} {nazwisko}. HASŁO TYMCZASOWE: {temp_password}', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            logging.getLogger("error").error(f"REGISTER_ERROR: {str(e)}", exc_info=True)

    return render_template('register.html')


def validate_password(password):
    """
        Walidator polityki haseł (Security Compliance).

        Wymusza na użytkownikach stosowanie silnych haseł podczas ich zmiany.
        Chroni przed atakami słownikowymi i tęczowymi (Rainbow Tables),
        wymuszając odpowiednią długość i złożoność znaków (zwiększając entropię hasła).

        **Reguły:**
        - Minimum 12 znaków.
        - Przynajmniej 2 duże litery [A-Z].
        - Przynajmniej 2 znaki specjalne (np. !@#).

        Args:
            password (str): Hasło w postaci jawnej (plain text) do sprawdzenia.

        Returns:
            bool: True, jeśli hasło spełnia wszystkie wymogi bezpieczeństwa.
    """
    if len(password) < 12:
        flash("Hasło jest krótsze niż 12 znaków.", 'warning')
        return False
    if len(re.findall(r'[A-Z]', password)) < 2:
        flash("Hasło zawiera mniej niż dwie duże litery.", 'warning')
        return False
    if len(re.findall(r'[!@#$%^&*(),.?":{}|<>]', password)) < 2:
        flash("Hasło zawiera mniej niż dwa znaki specjalne.", 'warning')
        return False
    return True


@auth_bp.route('/profil', methods=['GET', 'POST'])
@login_required
def profile():
    """
        Centrum zarządzania tożsamością użytkownika (Self-Service).

        Umożliwia zalogowanemu użytkownikowi samodzielną administrację swoim kontem
        bez angażowania administratora.

        **Obsługiwane Procesy:**
        1.  **Zmiana Hasła:**
            -   Wymaga podania starego hasła (re-authentication), co chroni przed zmianą
                hasła przez osobę, która znalazła odblokowany komputer (Session Riding).
            -   Weryfikuje siłę nowego hasła funkcją `validate_password`.
            -   Zapisuje nowy hash (scrypt) w bazie.

        2.  **Ustawienia Prywatności (RODO / GDPR):**
            -   Pozwala pilotowi zdecydować, czy jego nazwisko i licencja są widoczne
                na publicznych listach rankingowych i w raportach.
            -   Zmiana tych flag w bazie (`pdt_core.pilot`) natychmiast wpływa na
                dane zwracane przez moduł raportowy (anonimizacja).

        Returns:
            str: Widok profilu z formularzami edycji.
    """
    pilot_row = db.session.execute(text("SELECT * FROM pdt_core.pilot WHERE id_pilot = :id"),
                                   {'id': current_user.id_pilot}).fetchone()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'change_password':
            stare = request.form.get('stare_haslo')
            nowe = request.form.get('nowe_haslo')
            nowe_potw = request.form.get('nowe_haslo_confirm')

            if nowe:
                if not stare or not check_password_hash(current_user.haslo_hash, stare):
                    security_logger.warning("PWD_CHANGE_FAILURE", extra={
                        'event': 'CREDENTIAL_UPDATE_FAIL',
                        'user': current_user.login,
                        'src_ip': request.remote_addr,
                        'details': 'Błędne stare hasło przy próbie zmiany'
                    })
                    flash('Błędne stare hasło!', 'danger')
                elif nowe != nowe_potw:
                    flash('Nowe hasła nie są identyczne!', 'danger')
                elif not validate_password(nowe):
                    pass
                else:
                    hash_h = generate_password_hash(nowe)
                    db.session.execute(text("UPDATE pdt_auth.uzytkownik SET haslo_hash = :h WHERE id_uzytkownik = :id"),
                                       {'h': hash_h, 'id': current_user.id_uzytkownik})
                    db.session.commit()
                    security_logger.info("PWD_CHANGE_SUCCESS", extra={
                        'event': 'CREDENTIAL_UPDATE_SUCCESS',
                        'user': current_user.login,
                        'src_ip': request.remote_addr,
                        'details': 'Hasło zostało zmienione pomyślnie'
                    })
                    flash('Hasło zostało zmienione pomyślnie.', 'success')
                    return redirect(url_for('auth.profile'))

        elif action == 'save_rodo':
            if current_user.id_pilot:
                pokazywac_dane = 'pokazywac_dane' in request.form
                pokazywac_lic = 'pokazywac_lic' in request.form
                db.session.execute(text("""
                    UPDATE pdt_core.pilot
                    SET pokazywac_dane = :d,
                        pokazywac_licencje = :l
                    WHERE id_pilot = :id
                """), {'d': pokazywac_dane, 'l': pokazywac_lic, 'id': current_user.id_pilot})
                app_logger.info("PRIVACY_SETTINGS_UPDATED", extra={
                    'event': 'GDPR_UPDATE',
                    'user': current_user.login,
                    'src_ip': request.remote_addr,
                    'details': 'Użytkownik zaktualizował ustawienia RODO'
                })
                db.session.commit()
                flash('Ustawienia prywatności zostały zapisane!', 'success')
                return redirect(url_for('auth.profile'))

    return render_template('profile.html', pilot=pilot_row)