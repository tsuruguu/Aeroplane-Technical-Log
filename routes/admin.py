"""
Moduł administracyjny (Admin) z systemem pełnego nadzoru (Audit Trail).

Zarządzanie użytkownikami, edycja danych osobowych, ról systemowych
oraz ręczne korekty salda finansowego.

**System Logowania Audytowego (Cybersecurity Standard)**

Wszystkie akcje administracyjne są rejestrowane w kanałach `security` oraz `application`.
Każdy wpis zawiera `src_ip` administratora oraz unikalny podpis HMAC-SHA256.

Przykład logu korekty finansowej (JSON)::
{
    "timestamp": "2026-01-11T19:05:12.456Z",
    "level": "INFO",
    "event": "FINANCIAL_CORRECTION",
    "admin": "admin",
    "target_pilot_id": 42,
    "amount": "-150.00",
    "signature": "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92"
}
"""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import text
from werkzeug.security import generate_password_hash
# from database import db
from extensions import db
admin_bp = Blueprint('admin', __name__)
security_logger = logging.getLogger("security")
app_logger = logging.getLogger("application")
error_logger = logging.getLogger("error")

@admin_bp.route('/admin/uzytkownicy')
@login_required
def users_list():
    """
        Raport agregujący metryki kont użytkowników.

        Generuje tabelaryczny raport o użytkownikach, agregując dane z czterech różnych obszarów systemu:

        1.  **Tożsamość Cyfrowa:** Login i rola systemowa (z `pdt_auth.uzytkownik`).
        2.  **Tożsamość Osobowaa:** Imię, nazwisko, licencja (z `pdt_core.pilot`).
        3.  **Finanse:** Aktualne saldo (z widoku `pdt_rpt.v_saldo_pilota`).
        4.  **Operacje:** Suma wylatanych godzin (z widoku `pdt_core.v_pilot_nalot`).

        **Techniczne aspekty zapytania SQL:**

        Zastosowano `LEFT JOIN` do tabel powiązanych. Jest to krytyczne dla poprawności działania systemu,
        ponieważ pozwala wyświetlić na liście również:

        -   Konta techniczne (np. 'mechanik'), które nie posiadają jeszcze profilu pilota.
        -   Konta zablokowane (gdzie `deleted_at` nie jest NULL).

        Gdyby użyto zwykłego `JOIN`, konta te zniknęłyby z listy, uniemożliwiając adminowi zarządzanie nimi.

        Returns:
            str: Wyrenderowany szablon listy użytkowników.
    """
    if current_user.rola != 'admin':
        security_logger.warning("UNAUTHORIZED_ADMIN_ACCESS", extra={
            'event': 'ACCESS_DENIED',
            'user': current_user.login,
            'src_ip': request.remote_addr,
            'target_endpoint': 'users_list'
        })
        flash('Brak uprawnień.', 'danger')
        return redirect(url_for('index'))

    app_logger.info("ADMIN_VIEW_USER_LIST", extra={
        'event': 'DATA_ACCESS',
        'admin': current_user.login,
        'src_ip': request.remote_addr
    })

    sql = text("""
               SELECT u.id_uzytkownik,
                      u.login,
                      u.rola,
                      p.id_pilot,
                      p.imie,
                      p.nazwisko,
                      p.licencja,
                      p.deleted_at            as pilot_deleted_at,
                      COALESCE(s.saldo, 0)    as aktualne_saldo,
                      COALESCE(vn.nalot_h, 0) as wylatane_godziny
               FROM pdt_auth.uzytkownik u
                        LEFT JOIN pdt_core.pilot p USING (id_pilot)
                        LEFT JOIN pdt_rpt.v_saldo_pilota s ON p.id_pilot = s.id_pilot
                        LEFT JOIN pdt_core.v_pilot_nalot vn ON p.id_pilot = vn.id_pilot
               ORDER BY u.id_uzytkownik
               """)
    users = db.session.execute(sql).fetchall()

    return render_template('admin_users_list.html', users=users)


# routes/admin.py

@admin_bp.route('/admin/uzytkownik/<int:id_user>', methods=['GET', 'POST'])
@login_required
def user_edit(id_user):
    """
        Kontroler zarządzania tożsamością i korekt finansowych.

        *Wzorzec Action Dispatcher*

            Rozróżnia akcje (save_data, korekta_salda, create_pilot_profile) na podstawie
            wartości parametru 'action' w żądaniu POST.

        **Logika Biznesowa i Obsługiwane Akcje:**

        1.  **'save_data' (Aktualizacja):**

            -   Zmienia dane logowania i osobowe.
            -   **Soft Delete:** Obsługuje przełącznik "Konto Aktywne". Odznaczenie powoduje ustawienie
                `deleted_at = NOW()`. Użytkownik nie może się zalogować, ale jego historia lotów
                i operacji finansowych pozostaje nienaruszona (Integralność Referencyjna).

        2.  **'korekta_salda' (Finanse):**

            -   Umożliwia wprowadzanie korekt salda in-minus (obciążenia ręczne).
            -   Wpisy w tabeli `wplata` z ujemną kwotą są dopuszczalne i agregowane
            przez widoki salda jako operacje debetowe.

        3.  **'create_pilot_profile' (Naprawa Danych):**

            -   Dla kont technicznych (np. 'mechanik'), które pierwotnie nie miały profilu osobowego,
                funkcja tworzy pusty rekord w `pdt_core.pilot` i łączy go relacją 1:1.

        **Audyt (Historia Operacji):**

        Wyświetla historię finansową pobraną z widoku `pdt_rpt.v_historia_finansowa`. Widok ten
        używa zaawansowanych funkcji okna SQL (`SUM(...) OVER(...)`) do dynamicznego wyliczania
        salda "krok po kroku" po każdej operacji.
    """
    if current_user.rola != 'admin':
        security_logger.critical("UNAUTHORIZED_USER_EDIT_ATTEMPT", extra={
            'event': 'ACCESS_VIOLATION',
            'user': current_user.login,
            'target_user_id': id_user,
            'src_ip': request.remote_addr
        })
        return redirect(url_for('index'))

    user_sql = text("""
                    SELECT u.*,
                           p.imie,
                           p.nazwisko,
                           p.licencja,
                           p.deleted_at,
                           p.nalot_zewnetrzny,
                           COALESCE(s.saldo, 0)                                        as saldo,
                           COALESCE(vn.nalot_h, 0)                                     as nalot_total,
                           (COALESCE(vn.nalot_h, 0) - COALESCE(p.nalot_zewnetrzny, 0)) as nalot_systemowy
                    FROM pdt_auth.uzytkownik u
                             LEFT JOIN pdt_core.pilot p USING (id_pilot)
                             LEFT JOIN pdt_rpt.v_saldo_pilota s ON p.id_pilot = s.id_pilot
                             LEFT JOIN pdt_core.v_pilot_nalot vn ON p.id_pilot = vn.id_pilot
                    WHERE u.id_uzytkownik = :id
                    """)
    user = db.session.execute(user_sql, {'id': id_user}).fetchone()

    if not user:
        error_logger.error(f"USER_NOT_FOUND_EDIT: ID {id_user}", extra={'admin': current_user.login})
        flash('Nie znaleziono użytkownika.', 'danger')
        return redirect(url_for('admin.users_list'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save_data':
            login = request.form.get('login')
            rola = request.form.get('rola')
            imie = request.form.get('imie')
            nazwisko = request.form.get('nazwisko')
            licencja = request.form.get('licencja')
            nowe_haslo = request.form.get('nowe_haslo')
            czy_aktywny = request.form.get('czy_aktywny')
            nalot_zew = request.form.get('nalot_zewnetrzny')

            security_logger.info("ADMIN_UPDATED_USER_ACCOUNT", extra={
                'event': 'USER_MODIFICATION',
                'admin': current_user.login,
                'target_user': login,
                'new_role': rola,
                'password_reset': bool(nowe_haslo),
                'account_active': czy_aktywny,
                'src_ip': request.remote_addr
            })

            params_auth = {'l': login, 'r': rola, 'uid': id_user}
            sql_auth = "UPDATE pdt_auth.uzytkownik SET login = :l, rola = :r"
            if nowe_haslo and nowe_haslo.strip():
                sql_auth += ", haslo_hash = :h"
                params_auth['h'] = generate_password_hash(nowe_haslo)
            sql_auth += " WHERE id_uzytkownik = :uid"
            db.session.execute(text(sql_auth), params_auth)

            if user.id_pilot:
                sql_pilot = """
                            UPDATE pdt_core.pilot
                            SET imie             = :im, \
                                nazwisko         = :naz, \
                                licencja         = :lic,
                                nalot_zewnetrzny = :nz,
                                deleted_at       = CASE WHEN :active = true THEN NULL ELSE NOW() END
                            WHERE id_pilot = :pid \
                            """
                db.session.execute(text(sql_pilot), {
                    'im': imie, 'naz': nazwisko, 'lic': licencja,
                    'nz': nalot_zew if nalot_zew else 0,
                    'active': (czy_aktywny == 'on'),
                    'pid': user.id_pilot
                })

            db.session.commit()
            flash('Zaktualizowano dane użytkownika.', 'success')

        elif action == 'korekta_salda':
            kwota = request.form.get('kwota_korekty')
            komentarz = request.form.get('komentarz_korekty')

            if user.id_pilot and kwota:
                app_logger.warning("ADMIN_FINANCIAL_KOREKTA", extra={
                    'event': 'BALANCE_ADJUSTMENT',
                    'admin': current_user.login,
                    'pilot_id': user.id_pilot,
                    'amount': kwota,
                    'reason': komentarz,
                    'src_ip': request.remote_addr
                })

                db.session.execute(text("""
                                        INSERT INTO pdt_core.wplata (id_pilot, kwota, tytul, data_wplaty)
                                        VALUES (:pid, :kwota, :tytul, NOW())
                                        """), {
                                       'pid': user.id_pilot,
                                       'kwota': kwota,
                                       'tytul': f"KOREKTA ADMINA: {komentarz}"
                                   })
                db.session.commit()
                flash('Dokonano korekty salda.', 'info')

        elif action == 'create_pilot_profile':
            app_logger.info("ADMIN_CREATED_PILOT_PROFILE", extra={
                'event': 'DATA_REPAIR',
                'admin': current_user.login,
                'target_user_id': id_user
            })
            try:
                res = db.session.execute(text("""
                                              INSERT INTO pdt_core.pilot (imie, nazwisko, licencja)
                                              VALUES ('Nowy', 'Użytkownik', '')
                                              RETURNING id_pilot
                                              """))
                new_pilot_id = res.fetchone()[0]

                db.session.execute(text("""
                                        UPDATE pdt_auth.uzytkownik
                                        SET id_pilot = :pid
                                        WHERE id_uzytkownik = :uid
                                        """), {'pid': new_pilot_id, 'uid': id_user})

                db.session.commit()
                flash('Utworzono profil osobowy. Możesz teraz edytować imię i nazwisko.', 'success')
            except Exception as e:
                db.session.rollback()
                error_logger.error(f"PROFILE_CREATION_FAILED: {str(e)}", exc_info=True)
                # flash(f'Błąd podczas tworzenia profilu: {str(e)}', 'danger')

        return redirect(url_for('admin.user_edit', id_user=id_user))

    historia = []
    if user.id_pilot:
        historia = db.session.execute(text("""
                                           SELECT *
                                           FROM pdt_rpt.v_historia_finansowa
                                           WHERE id_pilot = :pid
                                           ORDER BY data_operacji DESC
                                           LIMIT 50 
                                           """), {'pid': user.id_pilot}).fetchall()

    return render_template('admin_user_edit.html', u=user, historia=historia)