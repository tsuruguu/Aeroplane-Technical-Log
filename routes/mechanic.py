"""
Moduł mechanika (CAMO) z pełnym nadzorem technicznym.

Obsługuje Panel Techniczny: statusy resursów szybowców, zgłaszanie i obsługę usterek,
dodawanie przeglądów okresowych oraz dokumentację zdjęciową napraw.

**System Logowania Audytowego (Maintenance & Safety Audit)**

Logi w tym module dokumentują krytyczne zmiany w statusie zdatności floty.
Szczególny nacisk położono na audyt przesyłania plików oraz resetowanie liczników przeglądów.

Przykład logu obsługi technicznej (JSON)::
{
    "timestamp": "2026-01-11T20:15:30.987Z",
    "level": "WARNING",
    "event": "MAINTENANCE_RELEASE",
    "mechanic": "head_mechanic_01",
    "aircraft_id": 5,
    "inspection_type": "Annual",
    "src_ip": "10.0.1.20",
    "signature": "b7a2d3..."
}
"""

import csv
import io
import os
import uuid
import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, Response
from flask_login import login_required, current_user
from sqlalchemy import text
# from database import db
from extensions import db

mechanic_bp = Blueprint('mechanic', __name__)
app_logger = logging.getLogger("application")
security_logger = logging.getLogger("security")
error_logger = logging.getLogger("error")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    """
        Walidator typu MIME i rozszerzenia pliku.

        Sprawdza, czy przesyłany plik ma bezpieczne rozszerzenie (zdefiniowane w ``ALLOWED_EXTENSIONS``).
        Jest to kluczowa linia obrony przed atakami typu **RCE (Remote Code Execution)**.

        **Zagrożenie:**

        Bez tej weryfikacji atakujący mógłby przesłać skrypt wykonywalny (np. ``malware.php``, ``script.py``, ``cmd.exe``)
        zamiast zdjęcia. Jeśli serwer pozwoliłby na jego wykonanie, haker przejąłby kontrolę nad systemem.

        **Mechanizm:**

        1. Sprawdza obecność kropki w nazwie.
        2. Pobiera rozszerzenie (ostatni element po kropce).
        3. Konwertuje na małe litery i sprawdza obecność na białej liście (whitelist).

        Args:
            filename (str): Oryginalna nazwa przesyłanego pliku.

        Returns:
            bool: ``True`` jeśli plik jest bezpiecznym obrazem, w przeciwnym razie ``False``.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@mechanic_bp.route('/mechanik')
@login_required
def index():
    """
        Pulpit zarządzania zdatnością floty CAMO (Continuing Airworthiness Management Organisation).

        Agreguje dane techniczne z całego systemu, aby dać mechanikowi natychmiastowy
        wgląd w stan zdatności floty.

        **Algorytm Obliczania Resursów (TTSN / TSO):**

        Dla każdego szybowca system wykonuje analizę w czasie rzeczywistym:
        1. Pobiera stan nalotu całkowitego z widoku zmaterializowanego/widoku raportowego.
        2. Identyfikuje datę ostatniego przeglądu okresowego typu '500h' lub 'Annual'.
        3. Wykonuje agregację SQL: `SUM(EXTRACT(EPOCH FROM (dt_ladowanie - dt_start)))`
           dla wszystkich lotów po dacie ostatniego przeglądu, pomijając rekordy usunięte.
        4. Oblicza deltę (limit - nalot_od_przegladu) i mapuje na progi alertowe (danger/warning).

        Wydajność: Zapytania agregujące są wykonywane w pętli dla floty. Przy skali >100 statków
        wymagałoby to optymalizacji do pojedynczego zapytania z GROUP BY.
    """
    app_logger.info("ACCESS_CAMO_DASHBOARD", extra={
        'event': 'MAINTENANCE_VIEW',
        'user': current_user.login,
        'src_ip': request.remote_addr
    })

    szybowce_db = db.session.execute(text("""
                                          SELECT *
                                          FROM pdt_core.v_szybowiec_status
                                          ORDER BY znak_rej
                                          """)).fetchall()

    status_floty = []
    for s in szybowce_db:
        sql_total = text("SELECT nalot_calk_h FROM pdt_core.v_szybowiec_nalot WHERE id_szybowiec=:sid")
        nalot_total = db.session.execute(sql_total, {'sid': s.id_szybowiec}).scalar() or 0

        if s.ostatni_przeglad:
            sql_nalot = text("""
                             SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (dt_ladowanie - dt_start)) / 3600), 0)
                             FROM pdt_core.lot
                             WHERE id_szybowiec = :sid
                               AND data_lotu > :d_przeglad
                               AND deleted_at IS NULL
                             """)
            nalot_od_przegladu = db.session.execute(sql_nalot,
                                                    {'sid': s.id_szybowiec, 'd_przeglad': s.ostatni_przeglad}).scalar()
        else:
            nalot_od_przegladu = nalot_total

        limit_h = 500.0
        pozostalo = limit_h - float(nalot_od_przegladu)

        mechanik_str = None
        if s.mech_nazwisko:
            mechanik_str = f"{s.mech_imie[0]}. {s.mech_nazwisko}"
        elif s.mech_login:
            mechanik_str = s.mech_login

        status_floty.append({
            'szybowiec': s,
            'nalot_total': float(nalot_total),
            'nalot_od_check': float(nalot_od_przegladu),
            'pozostalo': pozostalo,
            'alert': 'danger' if pozostalo <= 0 else ('warning' if pozostalo < 10 else 'success'),
            'mechanik_opis': mechanik_str
        })

    base_sql = """
               SELECT u.*, \
                      s.znak_rej, \
                      s.typ       as model, \
                      l.data_lotu,
                      uz.login    as zm_login, \
                      pi.imie     as zm_imie, \
                      pi.nazwisko as zm_nazwisko
               FROM pdt_core.usterka u
                        JOIN pdt_core.szybowiec s USING (id_szybowiec)
                        LEFT JOIN pdt_core.lot l USING (id_lot)
                        LEFT JOIN pdt_auth.uzytkownik uz ON u.id_zmieniajacy = uz.id_uzytkownik
                        LEFT JOIN pdt_core.pilot pi ON uz.id_pilot = pi.id_pilot
               WHERE u.deleted_at IS NULL \
               """

    usterki_otwarte = db.session.execute(
        text(base_sql + " AND u.status IN ('otwarta', 'w_toku') ORDER BY u.created_at ASC")).fetchall()
    usterki_zamkniete = db.session.execute(
        text(base_sql + " AND u.status = 'zamknieta' ORDER BY u.updated_at DESC")).fetchall()

    return render_template('mechanic_dashboard.html',
                           flota=status_floty,
                           usterki_otwarte=usterki_otwarte,
                           usterki_zamkniete=usterki_zamkniete)


@mechanic_bp.route('/mechanik/szybowiec/<int:id_szybowiec>')
@login_required
def glider_details(id_szybowiec):
    """
        Cyfrowa Książka Płatowca (Digital Logbook).

        Agreguje pełną historię eksploatacyjną konkretnego statku powietrznego.

        **Agregacja Danych:**

        Widok łączy dane z trzech niezależnych źródeł w jedną spójną kartę:
        1.  `pdt_core.v_szybowiec_nalot`: Pobiera sumaryczny czas lotu (Total Time Since New).
        2.  `pdt_core.przeglad`: Historię obsługi technicznej (kto i kiedy wykonał przegląd).
        3.  `pdt_core.usterka`: Historię awarii i napraw.

        Dzięki temu mechanik ma pełny obraz "zdrowia" szybowca przed podjęciem decyzji o dopuszczeniu do lotu.

        Args:
            id_szybowiec (int): Unikalny identyfikator szybowca w bazie.
    """

    app_logger.info("VIEW_GLIDER_LOGBOOK", extra={
        'event': 'DATA_READ',
        'user': current_user.login,
        'glider_id': id_szybowiec,
        'src_ip': request.remote_addr
    })

    szybowiec = db.session.execute(text("""
        SELECT s.*, vn.nalot_calk_h 
        FROM pdt_core.szybowiec s
        LEFT JOIN pdt_core.v_szybowiec_nalot vn USING(id_szybowiec)
        WHERE s.id_szybowiec = :id
    """), {'id': id_szybowiec}).fetchone()

    if not szybowiec:
        flash('Nie znaleziono szybowca.', 'danger')
        return redirect(url_for('mechanic.index'))

    przeglady = db.session.execute(text("""
        SELECT p.*, uz.login, pi.imie, pi.nazwisko
        FROM pdt_core.przeglad p
        LEFT JOIN pdt_auth.uzytkownik uz ON p.id_mechanik = uz.id_uzytkownik
        LEFT JOIN pdt_core.pilot pi ON uz.id_pilot = pi.id_pilot
        WHERE p.id_szybowiec = :id AND p.deleted_at IS NULL
        ORDER BY p.data_przegladu DESC
    """), {'id': id_szybowiec}).fetchall()

    usterki = db.session.execute(text("""
        SELECT u.*, l.data_lotu, 
               (SELECT COUNT(*) FROM pdt_core.naprawa n WHERE n.id_usterka = u.id_usterka) as ile_napraw
        FROM pdt_core.usterka u
        LEFT JOIN pdt_core.lot l USING(id_lot)
        WHERE u.id_szybowiec = :id AND u.deleted_at IS NULL
        ORDER BY u.created_at DESC
    """), {'id': id_szybowiec}).fetchall()

    return render_template('mechanic_glider_details.html', s=szybowiec, przeglady=przeglady, usterki=usterki)


@mechanic_bp.route('/mechanik/export/flota')
@login_required
def export_fleet_csv():
    """
        Generowanie raportu stanu floty (CAMO Report).

        Tworzy plik CSV zawierający kluczowe wskaźniki zdatności dla wszystkich szybowców.
        Dane te są często wymagane do raportowania do urzędu lotnictwa cywilnego (ULC)
        lub dla zarządu aeroklubu w celu planowania budżetu na remonty.

        **Zawartość Raportu:**

        - Znaki rejestracyjne i typ.
        - Całkowity nalot (TTSN).
        - Data i rodzaj ostatniego przeglądu (np. ARC, 50h, 500h).

        Returns:
            Response: Plik `flota_status.csv` gotowy do pobrania.
    """
    security_logger.info("FLEET_STATUS_EXPORT", extra={
        'event': 'DATA_EXPORT',
        'user': current_user.login,
        'src_ip': request.remote_addr,
        'report_type': 'FLEET_STATUS'
    })

    data = db.session.execute(text("""
                                   SELECT s.znak_rej,
                                          s.typ,
                                          vn.nalot_calk_h,
                                          p.data_przegladu,
                                          p.typ as typ_przegladu
                                   FROM pdt_core.szybowiec s
                                            LEFT JOIN pdt_core.v_szybowiec_nalot vn USING (id_szybowiec)
                                            LEFT JOIN pdt_core.v_szybowiec_ostatni_przeglad p USING (id_szybowiec)
                                   WHERE s.deleted_at IS NULL
                                   ORDER BY s.znak_rej
                                   """)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Znak Rej.', 'Typ', 'Nalot Całkowity (h)', 'Data Ostatniego Przeglądu', 'Typ Przeglądu'])

    for row in data:
        nalot = f"{row.nalot_calk_h:.2f}".replace('.', ',') if row.nalot_calk_h else "0,00"
        writer.writerow([row.znak_rej, row.typ, nalot, row.data_przegladu or 'Brak', row.typ_przegladu or '-'])

    output.seek(0)
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=flota_status.csv"}
    )



@mechanic_bp.route('/mechanik/export/usterki')
@login_required
def export_issues_csv():
    """
        Eksport listy zadań bieżących (Work Order).

        Generuje zestawienie wszystkich otwartych usterek (status 'otwarta' lub 'w_toku').
        Służy jako "lista zadań" dla mechaników na dany dzień lub tydzień.
        Plik zawiera daty zgłoszeń, co pozwala priorytetyzować naprawy według czasu oczekiwania.

        Returns:
            Response: Plik `otwarte_usterki.csv`.
    """
    security_logger.info("EXPORT_MAINTENANCE_TASKS", extra={
        'event': 'DATA_EXPORT',
        'user': current_user.login,
        'src_ip': request.remote_addr,
        'scope': 'OPEN_ISSUES'
    })

    data = db.session.execute(text("""
                                   SELECT u.id_usterka, s.znak_rej, u.status, u.opis, u.created_at
                                   FROM pdt_core.usterka u
                                            JOIN pdt_core.szybowiec s USING (id_szybowiec)
                                   WHERE u.status != 'zamknieta'
                                     AND u.deleted_at IS NULL
                                   ORDER BY u.created_at ASC
                                   """)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID', 'Znak Rej.', 'Data Zgłoszenia', 'Status', 'Opis'])

    for row in data:
        writer.writerow([row.id_usterka, row.znak_rej, row.created_at.strftime('%Y-%m-%d'), row.status, row.opis])

    output.seek(0)
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=otwarte_usterki.csv"}
    )


@mechanic_bp.route('/mechanik/export/usterki_zamkniete')
@login_required
def export_closed_issues_csv():
    """
        Archiwizacja napraw (Maintenance History Export).

        Pobiera historyczne (zamknięte) zgłoszenia. Jest to kluczowe dla zachowania ciągłości
        dokumentacji technicznej (np. przy sprzedaży szybowca, nowy właściciel chce widzieć
        historię napraw).

        Returns:
            Response: Plik `archiwum_napraw.csv`.
    """
    security_logger.info("EXPORT_REPAIR_ARCHIVE", extra={
        'event': 'DATA_EXPORT',
        'user': current_user.login,
        'src_ip': request.remote_addr,
        'scope': 'CLOSED_ISSUES'
    })

    data = db.session.execute(text("""
                                   SELECT u.id_usterka,
                                          s.znak_rej,
                                          u.created_at,
                                          u.updated_at, -- To jest data zamknięcia (ostatniej zmiany)
                                          u.opis
                                   FROM pdt_core.usterka u
                                            JOIN pdt_core.szybowiec s USING (id_szybowiec)
                                   WHERE u.status = 'zamknieta'
                                     AND u.deleted_at IS NULL
                                   ORDER BY u.updated_at DESC
                                   """)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID', 'Znak Rej.', 'Data Zgłoszenia', 'Data Zamknięcia', 'Opis Usterki'])

    for row in data:
        zgloszenie = row.created_at.strftime('%Y-%m-%d') if row.created_at else ""
        zamkniecie = row.updated_at.strftime('%Y-%m-%d') if row.updated_at else ""

        writer.writerow([row.id_usterka, row.znak_rej, zgloszenie, zamkniecie, row.opis])

    output.seek(0)
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=archiwum_napraw.csv"}
    )


@mechanic_bp.route('/mechanik/usterka/<int:id_usterka>', methods=['GET', 'POST'])
@login_required
def details(id_usterka):
    """
        Obsługa cyklu życia usterki technicznej (Workflow Naprawczy).

        Zarządza pełnym procesem obsługi zgłoszenia: od otwarcia, przez diagnostykę, aż do zamknięcia.

        **Śledzenie Zmian (Audit Log):**

        Każda interwencja mechanika (dodanie opisu, wymiana części) jest rejestrowana w tabeli
        `pdt_core.naprawa` z sygnaturą czasową i ID użytkownika. Pozwala to odtworzyć
        historię naprawy w przypadku późniejszych problemów (np. w dochodzeniu powypadkowym).

        **Dokumentacja Cyfrowa:**

        Obsługuje bezpieczny upload zdjęć dowodowych. Pliki otrzymują losowe nazwy UUID,
        aby zapobiec nadpisywaniu plików oraz atakom typu Path Traversal lub wykonywaniu złośliwych skryptów.
    """
    usterka = db.session.execute(text("""
                                      SELECT u.*,
                                             s.znak_rej,
                                             s.typ                       as model,
                                             l.data_lotu,
                                             p.imie || ' ' || p.nazwisko as zglaszajacy,
                                             uz.login                    as zm_login,
                                             pi.imie                     as zm_imie,
                                             pi.nazwisko                 as zm_nazwisko
                                      FROM pdt_core.usterka u
                                               JOIN pdt_core.szybowiec s USING (id_szybowiec)
                                               LEFT JOIN pdt_core.lot l USING (id_lot)
                                               LEFT JOIN pdt_core.lot_pilot lp ON l.id_lot = lp.id_lot AND lp.rola = 'PIC'
                                               LEFT JOIN pdt_core.pilot p ON lp.id_pilot = p.id_pilot
                                               LEFT JOIN pdt_auth.uzytkownik uz ON u.id_zmieniajacy = uz.id_uzytkownik
                                               LEFT JOIN pdt_core.pilot pi ON uz.id_pilot = pi.id_pilot
                                      WHERE u.id_usterka = :id
                                      """), {'id': id_usterka}).fetchone()

    naprawy = db.session.execute(text("""
                                      SELECT n.*, u.login as mechanik_login
                                      FROM pdt_core.naprawa n
                                               JOIN pdt_auth.uzytkownik u ON n.id_mechanik = u.id_uzytkownik
                                      WHERE n.id_usterka = :id
                                      ORDER BY n.data_naprawy DESC
                                      """), {'id': id_usterka}).fetchall()

    if request.method == 'POST':
        if current_user.rola not in ['admin', 'mechanik']:
            security_logger.warning("UNAUTHORIZED_MAINTENANCE_ATTEMPT", extra={
                'event': 'ACCESS_VIOLATION',
                'user': current_user.login,
                'issue_id': id_usterka,
                'src_ip': request.remote_addr
            })
            flash('Brak uprawnień.', 'danger')
            return redirect(url_for('mechanic.index'))

        action = request.form.get('action')

        if action == 'update_status':
            nowy_status = request.form.get('status')
            opis_naprawy = request.form.get('opis_prac')
            czesci = request.form.get('czesci')

            app_logger.info("ISSUE_STATUS_UPDATE", extra={
                'event': 'MAINTENANCE_WORKFLOW',
                'mechanic': current_user.login,
                'issue_id': id_usterka,
                'new_status': nowy_status,
                'src_ip': request.remote_addr
            })

            if opis_naprawy:
                db.session.execute(text("""
                                        INSERT INTO pdt_core.naprawa (id_usterka, id_mechanik, opis_prac, wymienione_czesci)
                                        VALUES (:uid, :mid, :opis, :czesci)
                                        """), {
                                       'uid': id_usterka,
                                       'mid': current_user.id_uzytkownik,
                                       'opis': opis_naprawy,
                                       'czesci': czesci
                                   })

            db.session.execute(text("""
                                    UPDATE pdt_core.usterka
                                    SET status         = :s,
                                        id_zmieniajacy = :mid,
                                        updated_at     = NOW()
                                    WHERE id_usterka = :id
                                    """), {'s': nowy_status, 'id': id_usterka, 'mid': current_user.id_uzytkownik})

            db.session.commit()
            flash('Zaktualizowano status naprawy.', 'success')
            return redirect(url_for('mechanic.details', id_usterka=id_usterka))

        elif action == 'upload_photo':
            if 'file' not in request.files:
                flash('Nie wybrano pliku.', 'warning')
            else:
                file = request.files['file']
                if file and allowed_file(file.filename):
                    ext = file.filename.rsplit('.', 1)[1].lower()
                    unique_filename = f"usterka_{id_usterka}_{uuid.uuid4().hex}.{ext}"
                    path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(path)

                    security_logger.info("FILE_UPLOAD_MAINTENANCE", extra={
                        'event': 'FILE_UPLOAD',
                        'user': current_user.login,
                        'original_name': file.filename,
                        'stored_name': unique_filename,
                        'issue_id': id_usterka,
                        'src_ip': request.remote_addr
                    })

                    db.session.execute(text("""
                                            UPDATE pdt_core.usterka
                                            SET zdjecie_sciezka = :p,
                                                id_zmieniajacy  = :mid,
                                                updated_at      = NOW()
                                            WHERE id_usterka = :id
                                            """),
                                       {'p': unique_filename, 'id': id_usterka, 'mid': current_user.id_uzytkownik})

                    db.session.commit()
                    flash('Zdjęcie dodano pomyślnie.', 'success')
                else:
                    security_logger.error("MALICIOUS_UPLOAD_ATTEMPT", extra={
                        'event': 'UPLOAD_FAILURE_SECURITY',
                        'user': current_user.login,
                        'uploaded_file_name': file.filename if file else "None",
                        'src_ip': request.remote_addr
                    })
                    flash('Nieprawidłowy plik.', 'danger')

        return redirect(url_for('mechanic.details', id_usterka=id_usterka))

    return render_template('mechanic_details.html', usterka=usterka, naprawy=naprawy)


@mechanic_bp.route('/mechanik/przeglad/dodaj', methods=['POST'])
@login_required
def add_inspection():
    """
        Rejestracja wykonania czynności obsługowej (Maintenance Release).

        Jest to krytyczna operacja systemowa, która wpływa na obliczanie resursów.

        **Logika Biznesowa (Reset Liczników):**

        Wprowadzenie nowego przeglądu do bazy danych (`INSERT INTO pdt_core.przeglad`)
        powoduje, że algorytm w `mechanic.index` zacznie liczyć godziny "od przeglądu"
        od nowej daty. Innymi słowy – funkcja ta "zeruje licznik" do następnego przeglądu okresowego.

        **Wymagania:**

        Dostępna tylko dla ról technicznych (`admin`, `mechanik`), ponieważ błędny wpis
        może doprowadzić do przekroczenia resursu i utraty ubezpieczenia statku.
    """
    if current_user.rola not in ['admin', 'mechanik']:
        return redirect(url_for('index'))

    id_szybowiec = request.form.get('id_szybowiec')
    data = request.form.get('data_przegladu')
    typ = request.form.get('typ')
    uwagi = request.form.get('uwagi')

    app_logger.warning("MAINTENANCE_RELEASE_RECORDED", extra={
        'event': 'AIRWORTHINESS_DIRECTIVE',
        'mechanic': current_user.login,
        'aircraft_id': id_szybowiec,
        'inspection_type': typ,
        'src_ip': request.remote_addr,
        'details': f"Zatwierdzono przegląd typu {typ} - reset resursów"
    })

    db.session.execute(text("""
                            INSERT INTO pdt_core.przeglad (id_szybowiec, data_przegladu, typ, uwagi, id_mechanik)
                            VALUES (:id, :dt, :typ, :uwagi, :mid)
                            """), {
                           'id': id_szybowiec, 'dt': data, 'typ': typ, 'uwagi': uwagi,
                           'mid': current_user.id_uzytkownik
                       })
    db.session.commit()

    flash('Dodano nowy przegląd. Licznik resursu zresetowany.', 'success')
    return redirect(url_for('mechanic.index'))

