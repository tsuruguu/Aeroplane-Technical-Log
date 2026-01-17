"""
Moduł zarządzania flotą szybowców (Gliders) z pełnym audytem operacyjnym.

Odpowiada za ewidencję statków powietrznych: wyświetlanie listy floty,
rejestrację nowych jednostek, edycję parametrów kosztowych oraz wycofywanie z eksploatacji (soft-delete).

**System Logowania Audytowego (Aviation Compliance)**

Każda zmiana we flocie (dodanie, edycja, usunięcie) jest logowana w formacie JSON
z metadanymi umożliwiającymi śledzenie sprawcy (traceability) oraz integralność dowodową.

Przykład logu dodania szybowca (JSON)::
{
    "timestamp": "2026-01-17T20:15:00.123Z",
    "level": "INFO",
    "event": "GLIDER_CREATED",
    "user": "admin_rumsze",
    "glider_reg": "SP-1001",
    "src_ip": "10.0.0.8",
    "signature": "a7b8c9..."
}
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import text
from extensions import db
import logging

gliders_bp = Blueprint('gliders', __name__)

app_logger = logging.getLogger("application")
security_logger = logging.getLogger("security")
error_logger = logging.getLogger("error")

@gliders_bp.route('/szybowce')
@login_required
def index():
    """
    Kontroler widoku floty szybowców (Widok Techniczno-Administracyjny).

    Prezentuje listę aktywnych jednostek uprawnionym użytkownikom (admin, mechanik).

    **Logika uprawnień**

    - Dostęp ograniczony do ról technicznych i administracyjnych.
    - Próba dostępu przez zwykłego pilota kończy się przekierowaniem i logiem naruszenia.

    **Optymalizacja**

    - Filtruje rekordy na poziomie bazy danych (deleted_at IS NULL).
    """
    if current_user.rola not in ['admin', 'mechanik']:
        security_logger.warning("UNAUTHORIZED_GLIDER_LIST_ACCESS", extra={
            'event': 'ACCESS_VIOLATION',
            'user': current_user.login,
            'src_ip': request.remote_addr,
            'details': 'Próba wejścia w panel zarządzania flotą bez uprawnień'
        })
        flash('Brak uprawnień do zarządzania flotą.', 'danger')
        return redirect(url_for('index'))

    app_logger.info("ACCESS_GLIDER_LIST", extra={
        'event': 'DATA_READ',
        'user': current_user.login,
        'src_ip': request.remote_addr
    })

    szybowce = db.session.execute(text("""
                                       SELECT *
                                       FROM pdt_core.szybowiec
                                       WHERE deleted_at IS NULL
                                       ORDER BY znak_rej
                                       """)).fetchall()
    return render_template('gliders_list.html', szybowce=szybowce)


@gliders_bp.route('/szybowce/dodaj', methods=['GET', 'POST'])
@login_required
def add():
    """
    Obsługuje proces rejestracji nowego statku powietrznego we flocie.

    **Bezpieczeństwo**

    - Weryfikacja unikalności znaku rejestracyjnego (klucz UNIQUE w bazie).
    - Logowanie transakcyjne utworzenia zasobu.

    **Przepływ Logiki**

    1. Walidacja roli użytkownika.
    2. Przetworzenie danych formularza (POST).
    3. Zapis do tabeli pdt_core.szybowiec.
    """
    if current_user.rola not in ['admin', 'mechanik']:
        return redirect(url_for('index'))

    if request.method == 'POST':
        znak = request.form.get('znak_rej')
        typ = request.form.get('typ')
        cena = request.form.get('cena_za_h')

        try:
            db.session.execute(text("""
                                    INSERT INTO pdt_core.szybowiec (znak_rej, typ, cena_za_h)
                                    VALUES (:z, :t, :c)
                                    """), {'z': znak, 't': typ, 'c': cena})
            db.session.commit()

            app_logger.info("GLIDER_CREATED", extra={
                'event': 'GLIDER_ADD',
                'user': current_user.login,
                'glider_reg': znak,
                'src_ip': request.remote_addr,
                'details': f'Dodano nowy szybowiec {znak} ({typ}) ze stawką {cena} PLN/h'
            })

            flash(f'Szybowiec {znak} został dodany do floty.', 'success')
            return redirect(url_for('gliders.index'))
        except Exception as e:
            db.session.rollback()
            error_logger.error(f"GLIDER_CREATION_FAILED: {str(e)}", exc_info=True, extra={
                'user': current_user.login,
                'glider_reg': znak
            })
            flash('Błąd: Znak rejestracyjny musi być unikalny!', 'danger')
            return redirect(url_for('gliders.add'))

    return render_template('glider_add.html')


@gliders_bp.route('/szybowce/edytuj/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    """
    Realizuje procedurę aktualizacji parametrów techniczno-finansowych szybowca.

    Umożliwia modyfikację stawki godzinowej oraz modelu bez niszczenia
    historycznych powiązań z wykonanymi lotami.

    **Audyt**

    - Każda zmiana ceny za godzinę jest rejestrowana jako zdarzenie ostrzegawcze (WARNING),
      gdyż wpływa na przyszłe rozliczenia członkowskie.
    """
    if current_user.rola not in ['admin', 'mechanik']:
        return redirect(url_for('index'))

    if request.method == 'POST':
        znak = request.form.get('znak_rej')
        typ = request.form.get('typ')
        cena = request.form.get('cena_za_h')

        try:
            db.session.execute(text("""
                                    UPDATE pdt_core.szybowiec
                                    SET znak_rej  = :z,
                                        typ       = :t,
                                        cena_za_h = :c
                                    WHERE id_szybowiec = :id
                                    """), {'z': znak, 't': typ, 'c': cena, 'id': id})
            db.session.commit()

            app_logger.warning("GLIDER_MODIFIED", extra={
                'event': 'GLIDER_UPDATE',
                'user': current_user.login,
                'glider_id': id,
                'glider_reg': znak,
                'src_ip': request.remote_addr,
                'changes': f'Nowa cena: {cena}, Model: {typ}'
            })

            flash('Zmiany w danych szybowca zostały zapisane.', 'success')
            return redirect(url_for('gliders.index'))
        except Exception as e:
            db.session.rollback()
            error_logger.error(f"GLIDER_UPDATE_FAILED: {id}, error: {str(e)}", exc_info=True)
            flash('Wystąpił błąd podczas aktualizacji danych.', 'danger')

    szybowiec = db.session.execute(text("SELECT * FROM pdt_core.szybowiec WHERE id_szybowiec = :id"),
                                   {'id': id}).fetchone()
    if not szybowiec:
        flash('Nie znaleziono szybowca.', 'danger')
        return redirect(url_for('gliders.index'))

    return render_template('glider_edit.html', s=szybowiec)


@gliders_bp.route('/szybowce/usun/<int:id>', methods=['POST'])
@login_required
def delete(id):
    """
    Wykonuje operację logicznego usunięcia szybowca z floty (Soft Delete).

    Wycofanie maszyny nie usuwa jej z bazy, aby zachować poprawność historyczną
    dzienników lotów i statystyk nalotu pilotów.

    **Bezpieczeństwo**

    - Operacja krytyczna: Dostępna wyłącznie dla roli 'admin'.
    - Mechanizm: Ustawienie kolumny deleted_at na NOW().
    """
    if current_user.rola != 'admin':
        security_logger.critical("UNAUTHORIZED_GLIDER_DELETE_ATTEMPT", extra={
            'event': 'ACCESS_VIOLATION',
            'user': current_user.login,
            'glider_id': id,
            'src_ip': request.remote_addr
        })
        flash('Tylko administrator może usuwać statki powietrzne.', 'danger')
        return redirect(url_for('gliders.index'))

    try:
        db.session.execute(text("UPDATE pdt_core.szybowiec SET deleted_at = NOW() WHERE id_szybowiec = :id"), {'id': id})
        db.session.commit()

        app_logger.warning("GLIDER_SOFT_DELETED", extra={
            'event': 'GLIDER_DELETE',
            'user': current_user.login,
            'glider_id': id,
            'src_ip': request.remote_addr
        })

        flash('Szybowiec został wycofany z eksploatacji.', 'warning')
    except Exception as e:
        db.session.rollback()
        error_logger.error(f"GLIDER_DELETE_FAILED: {id}, error: {str(e)}")

    return redirect(url_for('gliders.index'))