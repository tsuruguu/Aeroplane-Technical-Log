"""
Moduł obsługi lotów (Flights) z pełnym audytem operacyjnym.

Zarządza głównym dziennikiem lotów: wyświetlaniem listy, filtrowaniem, dodawaniem, edycją i usuwaniem (soft-delete) wpisów o lotach. Obsługuje również eksport danych do CSV.

**System Logowania Audytowego (Aviation Compliance)**

Każda operacja na dzienniku lotów jest logowana w formacie strukturyzowanym JSON.
Zmiany w nalotach i usterkach są traktowane jako zdarzenia krytyczne dla bezpieczeństwa operacji.

Przykład logu dodania lotu (JSON)::
{
    "timestamp": "2026-01-11T19:45:00.123Z",
    "level": "INFO",
    "event": "FLIGHT_RECORD_CREATED",
    "user": "pilot_kowalski",
    "flight_id": 1250,
    "aircraft": "SP-ABC",
    "src_ip": "10.0.0.5",
    "signature": "f29a88..."
}
"""

import io
import csv
import logging
import math
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from sqlalchemy import text
# from database import db
from extensions import db
flights_bp = Blueprint('flights', __name__)
app_logger = logging.getLogger("application")
security_logger = logging.getLogger("security")
error_logger = logging.getLogger("error")


def get_filtered_query_parts(args, user):
    """
        Generator bezpiecznych zapytań SQL.

        Dynamicznie konstruuje klauzulę WHERE oraz mapę parametrów dla silnika SQL.

        **Bezpieczeństwo**

        Implementuje wzorzec Query Builder w celu uniknięcia SQL Injection poprzez
        wymuszenie stosowania parametrów wiązanych (bind parameters).
        Krytycznym elementem jest sposób przekazywania wartości. Zamiast sklejać stringi (co grozi SQL Injection),
        funkcja zwraca tekst zapytania z placeholderami (np. `:fmodel`) oraz słownik parametrów.
        Silnik SQLAlchemy (korzystając z psycopg2) bezpiecznie "escapuje" te wartości przed wysłaniem do bazy.

        **Logika uprawnień (Row-Level Security emulation)**

        Dla użytkowników bez roli technicznej (admin/mechanik), zapytanie jest
        automatycznie rozszerzane o filtrację rekordów oznaczonych jako 'deleted',
        chyba że użytkownik jest właścicielem rekordu (p1 lub p2).

        Args:
            args (MultiDict): Obiekt request.args zawierający filtry z frontendu.
            user (Uzytkownik): Instancja aktualnie zalogowanego użytkownika.

        Returns:
            tuple: (str_where_clause, dict_params)
                - str_where_clause: Gotowy fragment SQL (np. "1=1 AND id_p1 = :fp1").
                - dict_params: Słownik mapujący placeholdery na zwalidowane wartości.
    """
    params = {}
    clauses = ["1=1"]

    pokaz_usuniete = args.get('pokaz_usuniete') == '1'
    if not pokaz_usuniete:
        clauses.append("deleted_at IS NULL")
    else:
        if user.rola not in ['admin', 'mechanik']:
            clauses.append("(deleted_at IS NULL OR (deleted_at IS NOT NULL AND (id_p1 = :uid OR id_p2 = :uid)))")
            params['uid'] = user.id_pilot

    p1 = args.get('filter_p1')
    if p1 and p1.strip():
        clauses.append("id_p1 = :fp1")
        params['fp1'] = int(p1)

    p2 = args.get('filter_p2')
    if p2 and p2.strip():
        clauses.append("id_p2 = :fp2")
        params['fp2'] = int(p2)

    szybowiec_id = args.get('filter_szybowiec_id')
    if szybowiec_id and szybowiec_id.strip():
        clauses.append("id_szybowiec = :fsid")
        params['fsid'] = int(szybowiec_id)

    model = args.get('filter_model')
    if model and model.strip():
        clauses.append("typ ILIKE :fmodel")
        params['fmodel'] = f"%{model.strip()}%"

    znak = args.get('filter_znak')
    if znak and znak.strip():
        clauses.append("znak_rej ILIKE :fznak")
        params['fznak'] = f"%{znak.strip()}%"

    start = args.get('filter_start')
    if start and start.strip():
        clauses.append("kod_startu = :fstart")
        params['fstart'] = start.strip()

    ladowanie = args.get('filter_ladowanie')
    if ladowanie and ladowanie.strip():
        clauses.append("kod_ladowania = :flad")
        params['flad'] = ladowanie.strip()

    data_lotu = args.get('filter_data')
    if data_lotu and data_lotu.strip():
        clauses.append("data_lotu = :fdata")
        params['fdata'] = data_lotu

    rodzaj_startu = args.get('filter_rodzaj_startu')
    if rodzaj_startu and rodzaj_startu.strip():
        clauses.append("rodzaj_startu = :frs")
        params['frs'] = rodzaj_startu

    usterka = args.get('filter_usterka')
    if usterka in ['TAK', 'NIE']:
        clauses.append("ma_usterke = :fust")
        params['fust'] = usterka

    zaloga = args.get('filter_zaloga')
    if zaloga == 'SOLO':
        clauses.append("id_p2 IS NULL")
    elif zaloga == 'DUAL':
        clauses.append("id_p2 IS NOT NULL")

    return " AND ".join(clauses), params


@flights_bp.route('/loty')
@login_required
def index():
    """
        Kontroler widoku dziennika lotów z implementacją stronicowania po stronie serwera (Widok Operacyjny).

        Odpowiada za prezentację danych operacyjnych z uwzględnieniem skomplikowanych
        reguł dostępu do danych osobowych (RODO/GDPR) oraz optymalizacji wydajności.

        **Proces przetwarzania**

        1. Agregacja uprawnień: Pobieranie list pilotów z uwzględnieniem flag RODO
           (pokazywac_dane) - filtruje dane na poziomie bazy, aby zminimalizować transfer.
        2. Paginacja: Wykorzystuje parametry LIMIT i OFFSET. Oblicza całkowitą liczbę
           rekordów w oddzielnym zapytaniu (count_sql) dla poprawnego renderowania paginatora.
        3. Optymalizacja: Dane pobierane są z widoku `pdt_rpt.v_dziennik_lotow`, który
           dokonuje wstępnych złączeń (JOIN) na poziomie silnika DB.

        **Zarządzanie Prywatnością**

        Listy rozwijane (dropdowny) z nazwiskami pilotów są generowane dynamicznie w zależności od roli:
        - **Admin/Mechanik:** Widzą pełną listę wszystkich osób w systemie.
        - **Zwykły Pilot:** Widzi na liście tylko siebie oraz tych pilotów, którzy w swoim profilu
          aktywnie wyrazili zgodę na przetwarzanie danych (`pokazywac_dane = true`).
          Zapobiega to nieuprawnionemu profilowaniu innych członków aeroklubu.

        **Optymalizacja Wydajności (Server-Side Pagination):**

        Zamiast pobierać całą historię lotów (która może liczyć tysiące rekordów) do pamięci RAM,
        funkcja realizuje stronicowanie po stronie bazy danych (`LIMIT ... OFFSET ...`).
        Redukuje to obciążenie serwera i czas ładowania strony.

        Returns:
            str: Wyrenderowany szablon HTML listy lotów z kontekstem filtrów i paginacji.
    """
    app_logger.info("ACCESS_FLIGHT_LOG", extra={
        'event': 'DATA_READ',
        'user': current_user.login,
        'src_ip': request.remote_addr,
        'page': request.args.get('page', 1)
    })

    if current_user.rola in ['admin', 'mechanik']:
        sql_pilots = text("SELECT id_pilot, imie, nazwisko, licencja FROM pdt_core.pilot ORDER BY nazwisko")
        all_pilots = db.session.execute(sql_pilots).fetchall()
    else:
        sql_pilots = text("""SELECT id_pilot, imie, nazwisko, licencja
                             FROM pdt_core.pilot
                             WHERE pokazywac_dane = true
                                OR id_pilot = :my_id
                             ORDER BY nazwisko""")
        all_pilots = db.session.execute(sql_pilots, {'my_id': current_user.id_pilot}).fetchall()

    all_gliders = db.session.execute(text("SELECT * FROM pdt_core.v_aktywne_szybowce ORDER BY znak_rej")).fetchall()
    all_airports = db.session.execute(
        text("SELECT * FROM pdt_core.lotnisko WHERE deleted_at IS NULL ORDER BY nazwa")).fetchall()

    page = request.args.get('page', 1, type=int)
    per_page = 50
    limit_last_n = request.args.get('limit_last_n', type=int)

    where_clause, params = get_filtered_query_parts(request.args, current_user)

    count_sql = f"SELECT COUNT(*) FROM pdt_rpt.v_dziennik_lotow WHERE {where_clause}"
    total_records = db.session.execute(text(count_sql), params).scalar()

    if limit_last_n and limit_last_n > 0:
        total_records = min(total_records, limit_last_n)

    total_pages = math.ceil(total_records / per_page)

    if page < 1: page = 1
    if page > total_pages and total_pages > 0: page = total_pages

    offset = (page - 1) * per_page

    data_sql = f"SELECT * FROM pdt_rpt.v_dziennik_lotow WHERE {where_clause} ORDER BY data_lotu DESC, id_lot DESC"

    final_limit = per_page

    if limit_last_n and limit_last_n > 0:
        remaining = limit_last_n - offset
        if remaining <= 0:
            final_limit = 0
        else:
            final_limit = min(per_page, remaining)

    data_sql += f" LIMIT :limit OFFSET :offset"
    params['limit'] = final_limit
    params['offset'] = offset

    loty = db.session.execute(text(data_sql), params).fetchall()

    args_without_page = request.args.copy()
    args_without_page.pop('page', None)
    return render_template('flights_list.html',
                           loty=loty,
                           all_pilots=all_pilots,
                           all_gliders=all_gliders,
                           all_airports=all_airports,
                           page=page,
                           total_pages=total_pages,
                           total_records=total_records,
                           args=args_without_page)


@flights_bp.route('/loty/export')
@login_required
def export_csv():
    """
        Generator raportów CSV z mechanizmem anonimizacji (Data Masking).

        Umożliwia pobranie aktualnie przefiltrowanego widoku tabeli do formatu Excel-CSV.

        **Logika Bezpieczeństwa (Anonimizacja):**

        System stosuje dynamiczne maskowanie danych wrażliwych w czasie rzeczywistym.
        Nawet jeśli użytkownik pobierze plik, nie zobaczy w nim danych, do których nie ma uprawnień.

        Reguły widoczności (Row-Level Security w warstwie aplikacji):

        1.  Jeśli jesteś **Adminem/Mechanikiem** -> Widzisz wszystko.
        2.  Jeśli jesteś **członkiem załogi** danego lotu -> Widzisz pełne dane tego lotu (koszty, nazwiska).
        3.  W przeciwnym razie -> Nazwiska innych pilotów i kwoty finansowe są zastępowane ciągiem `***`.

        Returns:
            Response: Strumień bajtów z plikiem CSV (kodowanie UTF-8-SIG dla Excela).
    """
    security_logger.info("DATA_EXPORT_CSV", extra={
        'event': 'DATA_EXFILTRATION_AUTHORIZED',
        'user': current_user.login,
        'src_ip': request.remote_addr,
        'filters': str(request.args.to_dict())
    })

    where_clause, params = get_filtered_query_parts(request.args, current_user)
    limit_last_n = request.args.get('limit_last_n', type=int)

    sql = f"SELECT * FROM pdt_rpt.v_dziennik_lotow WHERE {where_clause} ORDER BY data_lotu DESC, id_lot DESC"

    if limit_last_n and limit_last_n > 0:
        sql += f" LIMIT {limit_last_n}"

    result = db.session.execute(text(sql), params).fetchall()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    writer.writerow([
        'ID', 'Data', 'Znak Rej.', 'Model',
        'Pilot 1', 'Pilot 2', 'Rodzaj Startu',
        'Lotnisko Start', 'Lotnisko Ląd',
        'Start', 'Lądowanie', 'Nalot (h)',
        'Koszt (PLN)', 'Usterka'
    ])

    for row in result:
        is_priv = current_user.rola in ['admin', 'mechanik'] or current_user.id_pilot in [row.id_p1, row.id_p2]

        p1 = row.pilot_1 if (is_priv or row.id_p1 == current_user.id_pilot) else "***"
        p2 = row.pilot_2 if row.pilot_2 else ""
        if row.pilot_2 and not (is_priv or row.id_p2 == current_user.id_pilot):
            p2 = "***"

        koszt = f"{row.koszt_calkowity:.2f}".replace('.', ',') if is_priv else "***"

        writer.writerow([
            row.id_lot,
            row.data_lotu,
            row.znak_rej,
            row.typ,
            p1,
            p2,
            row.rodzaj_startu,
            row.kod_startu,
            row.kod_ladowania,
            row.dt_start.strftime('%H:%M') if row.dt_start else "",
            row.dt_ladowanie.strftime('%H:%M') if row.dt_ladowanie else "",
            f"{row.czas_h:.2f}".replace('.', ','),
            koszt,
            row.ma_usterke
        ])

    output.seek(0)
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=dziennik_lotow.csv"}
    )



@flights_bp.route('/loty/nowy', methods=['GET', 'POST'])
@login_required
def add_flight():
    """
        Obsługuje transakcję zapisu nowej operacji lotniczej.

        Funkcja ta odpowiada za wprowadzenie kompletnego zapisu o locie, dbając o spójność
        danych operacyjnych i finansowych.

        **Walidacja**

            - Implementuje regułę bezpieczeństwa: Jeśli pilotem dowódcą (PIC) jest UCZEŃ, system
              wymaga, aby w kabinie był instruktor LUB aby wskazano instruktora nadzorującego z ziemi.
              Zapobiega to zapisaniu nielegalnych operacji lotniczych.
            - Przechwytuje błędy integralności i wyjątki rzucane przez triggery bazy danych
              (np. nakładanie się czasów lotu szybowca).

        **Przebieg transakcji (ACID)**

            1. INSERT do `pdt_core.lot` -> pobranie generowanego ID.
            2. Opcjonalny INSERT do `pdt_core.usterka` (relacja 1:1).
            3. Iteracyjny INSERT do `pdt_core.lot_pilot` dla wszystkich członków załogi.
            4. Commit transakcji lub Rollback w przypadku dowolnego błędu IO/Logic.

        **Obsługa Błędów Domenowych:**

        Blok `try-except` jest skonfigurowany tak, aby przechwytywać błędy logiczne rzucane
        przez triggery w bazie danych (np. `RAISE EXCEPTION` gdy czas lądowania jest przed startem)
        i wyświetlać je użytkownikowi w zrozumiałym języku.
    """
    if request.method == 'POST':
        id_szybowiec = request.form.get('id_szybowiec')
        dt_start = request.form.get('dt_start')
        dt_ladowanie = request.form.get('dt_ladowanie')
        id_start = request.form.get('id_start')
        id_ladowanie = request.form.get('id_ladowanie')
        rodzaj_startu = request.form.get('rodzaj_startu')
        uwagi = request.form.get('uwagi')
        usterka = request.form.get('usterka')
        id_nadzorujacy = request.form.get('id_nadzorujacy') or None
        p1_id = request.form.get('id_pilot_1')
        p1_rola = request.form.get('rola_1')
        p2_id = request.form.get('id_pilot_2')
        p2_rola = request.form.get('rola_2')

        if p1_rola == 'UCZEN' and not p2_id and not id_nadzorujacy:
            flash('BŁĄD: Uczeń lecący samodzielnie (bez drugiej osoby) musi mieć nadzór z ziemi!', 'danger')
            return redirect(url_for('flights.add_flight'))

        try:
            res = db.session.execute(text("""
                                          INSERT INTO pdt_core.lot (id_szybowiec, dt_start, dt_ladowanie, kod_startu,
                                                                    kod_ladowania, rodzaj_startu, uwagi, id_nadzorujacy)
                                          VALUES (:s_id, :d_s, :d_l, :i_s, :i_l, :r_s, :uw, :nadzor)
                                          RETURNING id_lot
                                          """), {
                                         "s_id": id_szybowiec, "d_s": dt_start, "d_l": dt_ladowanie,
                                         "i_s": id_start, "i_l": id_ladowanie, "r_s": rodzaj_startu,
                                         "uw": uwagi, "nadzor": id_nadzorujacy
                                     })
            new_id_lot = res.fetchone()[0]
            app_logger.info("FLIGHT_CREATED", extra={
                'event': 'FLIGHT_RECORD_ADD',
                'user': current_user.login,
                'flight_id': new_id_lot,
                'glider_id': request.form.get('id_szybowiec'),
                'src_ip': request.remote_addr
            })

            if usterka and usterka.strip():
                db.session.execute(text("""
                                        INSERT INTO pdt_core.usterka (id_lot, id_szybowiec, opis, status)
                                        VALUES (:l_id, :s_id, :op, 'otwarta')
                                        """), {"l_id": new_id_lot, "s_id": id_szybowiec, "op": usterka.strip()})

            db.session.execute(text("""
                                    INSERT INTO pdt_core.lot_pilot (id_lot, id_pilot, rola)
                                    VALUES (:l_id, :p_id, :rola)
                                    """), {"l_id": new_id_lot, "p_id": p1_id, "rola": p1_rola})

            if p2_id and p2_rola:
                db.session.execute(text("""
                                        INSERT INTO pdt_core.lot_pilot (id_lot, id_pilot, rola)
                                        VALUES (:l_id, :p_id, :rola)
                                        """), {"l_id": new_id_lot, "p_id": p2_id, "rola": p2_rola})

            db.session.commit()
            flash('Lot zapisany poprawnie.', 'success')
            return redirect(url_for('flights.index'))
        except Exception as e:
            db.session.rollback()
            error_logger.error(f"FLIGHT_CREATION_FAILED: {str(e)}", exc_info=True, extra={'user': current_user.login})
            flash('Wystąpił błąd podczas zapisu lotu.', 'danger')

    szybowce = db.session.execute(text("SELECT * FROM pdt_core.v_aktywne_szybowce")).fetchall()
    lotniska = db.session.execute(text("SELECT * FROM pdt_core.lotnisko WHERE deleted_at IS NULL")).fetchall()
    piloci = db.session.execute(
        text("SELECT * FROM pdt_core.pilot WHERE deleted_at IS NULL ORDER BY nazwisko")).fetchall()

    return render_template('flights_add.html', szybowce=szybowce, lotniska=lotniska, piloci=piloci)


@flights_bp.route('/loty/edytuj/<int:id_lot>', methods=['GET', 'POST'])
@login_required
def edit_flight(id_lot):
    """
        Realizuje procedurę korekty historycznej zapisu operacji lotniczej.

        Umożliwia modyfikację istniejącego wpisu z zachowaniem jego ID, co jest kluczowe
        dla spójności logów systemowych i powiązań z usterkami.

        **Bezpieczeństwo (Authorization Check):**

        Przed wykonaniem jakiejkolwiek akcji system weryfikuje własność rekordu.
        Edytować lot może tylko Administrator lub pilot biorący w nim udział (PIC/SIC).
        Próba edycji cudzego lotu przez zwykłego użytkownika kończy się blokadą.

        **Strategia Aktualizacji Danych (Delete-Insert Pattern):**

        Aktualizacja składu załogi (relacja wiele-do-wielu w tabeli `lot_pilot`) jest realizowana
        poprzez usunięcie wszystkich starych powiązań dla tego lotu i wstawienie nowych.
        Jest to podejście bardziej robustne (odporne na błędy) niż próbkowanie różnic (diffing),
        eliminując ryzyko pozostawienia "duchów" (nieaktualnych pilotów) w załodze.

        **Obsługa Usterek:**

        Funkcja inteligentnie zarządza powiązaną usterką:
        - Jeśli usterka już istniała -> Aktualizuje jej opis.
        - Jeśli nie istniała, a użytkownik ją dodał -> Tworzy nowy rekord w `pdt_core.usterka`.
    """
    lot = db.session.execute(text("SELECT * FROM pdt_rpt.v_dziennik_lotow WHERE id_lot = :id"),
                             {'id': id_lot}).fetchone()
    if not lot:
        flash('Nie znaleziono lotu.', 'danger')
        return redirect(url_for('flights.index'))

    is_owner = current_user.id_pilot in [lot.id_p1, lot.id_p2]
    if current_user.rola != 'admin' and not is_owner:
        security_logger.warning("UNAUTHORIZED_FLIGHT_EDIT_ATTEMPT", extra={
            'event': 'ACCESS_VIOLATION',
            'user': current_user.login,
            'flight_id': id_lot,
            'src_ip': request.remote_addr
        })
        flash('Nie masz uprawnień do edycji tego lotu.', 'danger')
        return redirect(url_for('flights.index'))

    if request.method == 'POST':
        id_szybowiec = request.form.get('id_szybowiec')
        dt_start = request.form.get('dt_start')
        dt_ladowanie = request.form.get('dt_ladowanie')
        id_start = request.form.get('id_start')
        id_ladowanie = request.form.get('id_ladowanie')
        rodzaj_startu = request.form.get('rodzaj_startu')
        uwagi = request.form.get('uwagi')
        usterka_opis = request.form.get('usterka')
        id_nadzorujacy = request.form.get('id_nadzorujacy') or None
        p1_id = request.form.get('id_pilot_1')
        p1_rola = request.form.get('rola_1')
        p2_id = request.form.get('id_pilot_2')
        p2_rola = request.form.get('rola_2')

        app_logger.warning("FLIGHT_MODIFIED", extra={
            'event': 'FLIGHT_RECORD_UPDATE',
            'user': current_user.login,
            'flight_id': id_lot,
            'src_ip': request.remote_addr,
            'changes': str(request.form.to_dict(flat=True))
        })

        if p1_rola == 'UCZEN' and not p2_id and not id_nadzorujacy:
            flash('BŁĄD: Uczeń lecący samodzielnie musi mieć nadzór z ziemi!', 'danger')
            return redirect(url_for('flights.edit_flight', id_lot=id_lot))

        try:
            db.session.execute(text("""
                                    UPDATE pdt_core.lot
                                    SET id_szybowiec=:s_id,
                                        dt_start=:d_s,
                                        dt_ladowanie=:d_l,
                                        kod_startu=:i_s,
                                        kod_ladowania=:i_l,
                                        rodzaj_startu=:r_s,
                                        uwagi=:uw,
                                        id_nadzorujacy=:nadzor
                                    WHERE id_lot = :id
                                    """), {
                                   "s_id": id_szybowiec, "d_s": dt_start, "d_l": dt_ladowanie, "i_s": id_start,
                                   "i_l": id_ladowanie, "r_s": rodzaj_startu, "uw": uwagi,
                                   "nadzor": id_nadzorujacy, "id": id_lot
                               })

            if usterka_opis and usterka_opis.strip():
                istnieje = db.session.execute(text("SELECT id_usterka FROM pdt_core.usterka WHERE id_lot = :id"),
                                              {'id': id_lot}).fetchone()
                if istnieje:
                    db.session.execute(
                        text("UPDATE pdt_core.usterka SET opis = :op, id_szybowiec = :s_id WHERE id_lot = :id"),
                        {"op": usterka_opis.strip(), "s_id": id_szybowiec, "id": id_lot})
                else:
                    db.session.execute(text(
                        "INSERT INTO pdt_core.usterka (id_lot, id_szybowiec, opis, status) VALUES (:id, :s_id, :op, 'otwarta')"),
                                       {"id": id_lot, "s_id": id_szybowiec, "op": usterka_opis.strip()})

            db.session.execute(text("DELETE FROM pdt_core.lot_pilot WHERE id_lot = :id"), {'id': id_lot})
            db.session.execute(
                text("INSERT INTO pdt_core.lot_pilot (id_lot, id_pilot, rola) VALUES (:l_id, :p_id, :rola)"),
                {"l_id": id_lot, "p_id": p1_id, "rola": p1_rola})
            if p2_id and p2_rola:
                db.session.execute(
                    text("INSERT INTO pdt_core.lot_pilot (id_lot, id_pilot, rola) VALUES (:l_id, :p_id, :rola)"),
                    {"l_id": id_lot, "p_id": p2_id, "rola": p2_rola})

            db.session.commit()
            flash(f'Lot #{id_lot} został zaktualizowany.', 'success')
            return redirect(url_for('flights.index'))

        except Exception as e:
            db.session.rollback()
            error_logger.error(f"FLIGHT_UPDATE_FAILED: {id_lot}, error: {str(e)}", exc_info=True)
            return redirect(url_for('flights.edit_flight', id_lot=id_lot))

    piloci_lotu = db.session.execute(text("SELECT * FROM pdt_core.lot_pilot WHERE id_lot = :id"),
                                     {'id': id_lot}).fetchall()
    current_p1 = next((p for p in piloci_lotu if p.rola in ['PIC', 'UCZEN']), None)
    current_p2 = next((p for p in piloci_lotu if p.rola in ['SIC', 'INSTRUKTOR', 'PASAZER']), None)
    szybowce = db.session.execute(text("SELECT * FROM pdt_core.v_aktywne_szybowce")).fetchall()
    lotniska = db.session.execute(text("SELECT * FROM pdt_core.lotnisko WHERE deleted_at IS NULL")).fetchall()
    piloci = db.session.execute(
        text("SELECT * FROM pdt_core.pilot WHERE deleted_at IS NULL ORDER BY nazwisko")).fetchall()

    return render_template('flights_edit.html', lot=lot, szybowce=szybowce, lotniska=lotniska, piloci=piloci,
                           current_p1=current_p1, current_p2=current_p2)


@flights_bp.route('/loty/usun/<int:id_lot>', methods=['POST'])
@login_required
def delete_flight(id_lot):
    """
        Wykonuje operację logicznego usunięcia rekordu (Soft Delete).

        W systemach księgowych i operacyjnych usuwanie fizyczne (`DELETE FROM`) jest niedopuszczalne,
        ponieważ niszczy historię i audytowalność.

        **Mechanizm:**

        Zamiast usuwać rekord, funkcja ustawia kolumnę `deleted_at` na bieżący czas (`NOW()`).

        **Konsekwencje w systemie:**

        1.  **Widoki Raportowe:** Wszystkie widoki finansowe (`v_rozliczenie_finansowe`) i statystyczne
            mają warunek `WHERE deleted_at IS NULL`. Dzięki temu "usunięty" lot automatycznie przestaje
            być wliczany do salda pilota i nalotu szybowca.
        2.  **Audyt:** Rekord fizycznie pozostaje w bazie, co pozwala administratorowi sprawdzić historię
            edycji/usuwania w przypadku sporów.
    """
    lot = db.session.execute(text("SELECT * FROM pdt_rpt.v_dziennik_lotow WHERE id_lot = :id"),
                             {'id': id_lot}).fetchone()
    if not lot:
        flash('Nie znaleziono lotu.', 'danger')
        return redirect(url_for('flights.index'))
    is_owner = current_user.id_pilot in [lot.id_p1, lot.id_p2]
    if current_user.rola != 'admin' and not is_owner:
        security_logger.critical("UNAUTHORIZED_FLIGHT_DELETE_ATTEMPT", extra={
            'event': 'ACCESS_VIOLATION',
            'user': current_user.login,
            'flight_id': id_lot,
            'src_ip': request.remote_addr
        })
        flash('Nie masz uprawnień do usunięcia tego lotu.', 'danger')
        return redirect(url_for('flights.index'))
    try:
        app_logger.warning("FLIGHT_SOFT_DELETED", extra={
            'event': 'FLIGHT_RECORD_DELETE',
            'user': current_user.login,
            'flight_id': id_lot,
            'src_ip': request.remote_addr
        })
        db.session.execute(text("UPDATE pdt_core.lot SET deleted_at = NOW() WHERE id_lot = :id"), {"id": id_lot})
        db.session.execute(text("UPDATE pdt_core.usterka SET deleted_at = NOW() WHERE id_lot = :id"), {"id": id_lot})
        db.session.commit()
        flash(f'Lot #{id_lot} został pomyślnie usunięty.', 'success')
    except Exception as e:
        db.session.rollback()
        error_logger.error(f"FLIGHT_DELETE_FAILED: {id_lot}, error: {str(e)}")
    return redirect(url_for('flights.index'))