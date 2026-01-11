from app import create_app
from database import db
from sqlalchemy import text
from werkzeug.security import generate_password_hash

app = create_app()


def add_user(login, password, role, pilot_id=None):
    hashed = generate_password_hash(password)

    # 1. Sprawdź, czy istnieje użytkownik przypisany do tego pilota (np. Marek, id_pilot=4)
    user_with_pilot = None
    if pilot_id is not None:
        user_with_pilot = db.session.execute(
            text("SELECT id_uzytkownik FROM pdt_auth.uzytkownik WHERE id_pilot = :p"),
            {"p": pilot_id}
        ).fetchone()

    # 2. Sprawdź, czy istnieje użytkownik o takim loginie (np. 'admin')
    user_with_login = db.session.execute(
        text("SELECT id_uzytkownik FROM pdt_auth.uzytkownik WHERE login = :l"),
        {"l": login}
    ).fetchone()

    # LOGIKA ROZWIĄZYWANIA KONFLIKTÓW

    # A. Sytuacja konfliktowa:
    # Chcemy przypisać login 'admin' do pilota 4 (Marek), ale login 'admin' ma już ktoś inny (np. stare konto admina ID 1).
    # Musimy usunąć tego "starego" admina (ID 1), żeby zwolnić nazwę loginu dla Marka.
    if user_with_pilot and user_with_login:
        if user_with_pilot[0] != user_with_login[0]:
            print(
                f"⚠️ Konflikt loginów! Usuwam starego użytkownika '{login}' (ID: {user_with_login[0]}), aby przejąć login.")
            # Zakładamy, że stary admin (ID 1) nie ma przypisanych usterek, więc można go usunąć.
            # Jeśli on też ma usterki, trzeba by zrobić UPDATE loginu starego admina na np. 'admin_old', ale tu zakładamy delete.
            db.session.execute(text("DELETE FROM pdt_auth.uzytkownik WHERE id_uzytkownik = :id"),
                               {"id": user_with_login[0]})
            user_with_login = None  # Resetujemy zmienną, bo usera już nie ma

    # B. Wykonujemy UPDATE lub INSERT
    if user_with_pilot:
        # WAŻNE: Aktualizujemy istniejącego użytkownika pilota (zachowuje ID i nie psuje usterek!)
        uid = user_with_pilot[0]
        db.session.execute(text("""
                                UPDATE pdt_auth.uzytkownik
                                SET login      = :l,
                                    haslo_hash = :h,
                                    rola       = :r
                                WHERE id_uzytkownik = :uid
                                """), {"l": login, "h": hashed, "r": role, "uid": uid})
        print(f"✅ Zaktualizowano użytkownika (ID: {uid}) dla pilota {pilot_id} -> Login zmienił się na: {login}")

    elif user_with_login:
        # UPDATE istniejącego użytkownika po loginie (np. aktualizacja hasła dla 'mechanik')
        uid = user_with_login[0]
        db.session.execute(text("""
                                UPDATE pdt_auth.uzytkownik
                                SET haslo_hash = :h,
                                    rola       = :r,
                                    id_pilot   = :p
                                WHERE id_uzytkownik = :uid
                                """), {"l": login, "h": hashed, "r": role, "p": pilot_id, "uid": uid})
        print(f"✅ Zaktualizowano hasło/rolę dla loginu: {login} (ID: {uid})")

    else:
        # INSERT (Całkowicie nowy użytkownik)
        db.session.execute(text("""
                                INSERT INTO pdt_auth.uzytkownik (login, haslo_hash, rola, id_pilot)
                                VALUES (:l, :h, :r, :p)
                                """), {"l": login, "h": hashed, "r": role, "p": pilot_id})
        print(f"✅ Dodano nowego użytkownika: {login}")


with app.app_context():
    print("--- Rozpoczynam inteligentną naprawę użytkowników ---")

    # 1. Administrator (Przypisujemy mu id_pilot 4 - to przejmie konto Marka i zrobi z niego Admina)
    add_user('admin', 'admin123', 'admin', 4)

    # 2. Pilot Jan (id_pilot 1)
    add_user('jan_pilot', 'jan123', 'pilot', 1)

    # 3. Pilot Dobi (id_pilot 2) - Anna Nowak
    add_user('dobi_pilot', 'dobi123', 'pilot', 2)

    # 4. Mechanik (bez powiązania z pilotem - tu login mechanik)
    add_user('mechanik', 'mech123', 'mechanik', None)

    db.session.commit()
    print("\nGotowe! Baza użytkowników została zaktualizowana bez usuwania powiązań.")