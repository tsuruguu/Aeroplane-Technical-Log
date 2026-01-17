"""
Moduł raportów i statystyk z rozbudowanym audytem dostępu.

Generuje zestawienia finansowe, rankingi nalotów pilotów, statystyki szybowców
oraz umożliwia eksport tych danych do plików CSV.

**System Logowania Audytowego (Data Privacy Audit)**

Wszystkie operacje eksportu są traktowane jako zdarzenia wysokiego ryzyka i logowane
do kanału `security` z uwzględnieniem filtrów RODO i IP sprawcy.

Przykład logu eksportu finansowego (JSON)::
{
    "timestamp": "2026-01-11T20:45:12.123Z",
    "level": "INFO",
    "event": "FINANCIAL_DATA_EXPORT",
    "user": "admin_jan",
    "report": "saldo_pilota.csv",
    "src_ip": "192.168.1.100",
    "signature": "df8a92..."
}
"""

import io
import csv
import logging
from flask import Blueprint, render_template, Response, request
from flask_login import login_required, current_user
from sqlalchemy import text
# from database import db
from extensions import db
reports_bp = Blueprint('reports', __name__)
app_logger = logging.getLogger("application")
security_logger = logging.getLogger("security")
error_logger = logging.getLogger("error")

@reports_bp.route('/raporty')
@login_required
def dashboard():
    """
        Centrum analityki operacyjno-finansowej systemu.

        Prezentuje zagregowane dane, wykorzystując moc obliczeniową silnika bazy danych (PostgreSQL).

        **Optymalizacja Wydajności:**

        Zamiast pobierać tysiące rekordów lotów do Pythona i sumować je w pętli,
        funkcja korzysta z gotowych widoków SQL (`pdt_rpt...` i `pdt_core...`).
        Baza danych wykonuje agregacje (`SUM`, `COUNT`, `GROUP BY`) znacznie szybciej,
        a Python otrzymuje tylko gotowe wyniki do wyświetlenia.

        **Logika Finansowa:**

        Sekcja "Dłużnicy" i "Saldo" opiera się na widoku `v_rozliczenie_finansowe`, który
        dynamicznie wylicza koszt każdego lotu w oparciu o cennik szybowca, rodzaj startu
        oraz rolę pilota (np. podział kosztów 50/50 w locie koleżeńskim).
    """
    app_logger.info("ACCESS_REPORTS_DASHBOARD", extra={
        'event': 'ANALYTICS_VIEW',
        'user': current_user.login,
        'src_ip': request.remote_addr
    })

    if current_user.rola == 'admin':
        sql_piloci = text("""
                          SELECT id_pilot, imie, nazwisko, licencja, nalot_h, pokazywac_dane, pokazywac_licencje
                          FROM pdt_core.v_pilot_nalot
                          ORDER BY nalot_h DESC
                          """)
    else:
        sql_piloci = text("SELECT * FROM pdt_core.v_pilot_nalot ORDER BY nalot_h DESC")

    piloci_raw = db.session.execute(sql_piloci).fetchall()

    # Przetwarzanie na słowniki (Logika: Marta widzi Martę)
    piloci = []
    for p in piloci_raw:
        p_dict = dict(p._mapping)
        if p_dict.get('id_pilot') == current_user.id_pilot:
            p_dict['pokazywac_dane'] = True
            p_dict['pokazywac_licencje'] = True
        piloci.append(p_dict)

    my_stats = {'rank': '-', 'hours': 0.0}
    for index, p in enumerate(piloci):
        if p.get('id_pilot') == current_user.id_pilot:
            my_stats['rank'] = index + 1
            my_stats['hours'] = p.get('nalot_h', 0.0)
            break

    szybowce = db.session.execute(
        text("SELECT * FROM pdt_core.v_szybowiec_nalot ORDER BY CAST(nalot_calk_h AS FLOAT) DESC")
    ).fetchall()

    query_params = {'p_id': current_user.id_pilot}
    if current_user.rola == 'admin':
        sql_finanse = text("""
                           SELECT r.*, d.pilot_1, d.pilot_2
                           FROM pdt_rpt.v_rozliczenie_finansowe r
                                    JOIN pdt_rpt.v_dziennik_lotow d USING (id_lot)
                           WHERE r.kwota_do_zaplaty > 0
                             AND r.deleted_at IS NULL
                           ORDER BY r.id_lot DESC
                           """)
        sql_sumy = text("SELECT * FROM pdt_rpt.v_saldo_pilota ORDER BY saldo ASC")
    else:
        sql_finanse = text("""
                           SELECT r.*, d.pilot_1, d.pilot_2
                           FROM pdt_rpt.v_rozliczenie_finansowe r
                                    JOIN pdt_rpt.v_dziennik_lotow d USING (id_lot)
                           WHERE r.kwota_do_zaplaty > 0
                             AND r.id_pilot = :p_id
                             AND r.deleted_at IS NULL
                           ORDER BY r.id_lot DESC
                           """)
        sql_sumy = text("SELECT * FROM pdt_rpt.v_saldo_pilota WHERE id_pilot = :p_id")

    dluznicy = db.session.execute(sql_finanse, query_params).fetchall()
    sumy_dlugow = db.session.execute(sql_sumy, query_params).fetchall()
    total_cost_sum = sum(row.kwota_do_zaplaty for row in dluznicy)

    return render_template('reports_dashboard.html',
                           piloci=piloci, szybowce=szybowce, dluznicy=dluznicy,
                           sumy_dlugow=sumy_dlugow, my_stats=my_stats, total_cost_sum=total_cost_sum)


@reports_bp.route('/raporty/export/piloci')
@login_required
def export_piloci_csv():
    """
        Eksport rankingu nalotów z filtrowaniem prywatności.

        Generuje plik CSV z listą pilotów i ich wylatanymi godzinami.

        **Logika RODO (Data Masking):**

        Funkcja sprawdza rolę pobierającego:

        - **Admin:** Otrzymuje pełną listę z imionami i nazwiskami.
        - **Zwykły Użytkownik:** Otrzymuje listę, na której dane pilotów, którzy nie wyrazili
          zgody (`pokazywac_dane = false`), są zastąpione gwiazdkami (`***`).
          Dzięki temu zachowana jest transparentność rankingu (widać, że ktoś ma X godzin),
          ale chroniona jest tożsamość osób dbających o prywatność.
    """
    security_logger.info("EXPORT_PILOT_RANKING", extra={
        'event': 'DATA_EXPORT_PII',
        'user': current_user.login,
        'src_ip': request.remote_addr,
        'pii_masked': current_user.rola != 'admin'
    })

    if current_user.rola == 'admin':
        sql = text("""
                   SELECT imie, nazwisko, licencja, nalot_h, true as pokazywac_dane, true as pokazywac_licencje
                   FROM pdt_core.v_pilot_nalot
                   ORDER BY nalot_h DESC
                   """)
        res = db.session.execute(sql).fetchall()
    else:
        sql = text("SELECT * FROM pdt_core.v_pilot_nalot ORDER BY nalot_h DESC")
        res = db.session.execute(sql).fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Imię', 'Nazwisko', 'Licencja', 'Nalot (h)'])

    for p in res:
        if current_user.rola == 'admin' or p.id_pilot == current_user.id_pilot or p.pokazywac_dane:
            fname, lname = p.imie, p.nazwisko
        else:
            fname, lname = "***", "***"

        lic = p.licencja if (current_user.rola == 'admin' or p.id_pilot == current_user.id_pilot or p.pokazywac_licencje) else "***"
        nalot_h = f"{p.nalot_h:.2f}".replace('.', ',')
        writer.writerow([fname, lname, lic, nalot_h])

    return generate_csv_response(output, "ranking_pilotow.csv")


@reports_bp.route('/raporty/export/finanse')
@login_required
def export_finanse_csv():
    """
        Szczegółowy wyciąg operacji lotniczych (Billing Export).

        Generuje zestawienie wszystkich lotów obciążających konto użytkownika.

        **Zastosowanie:**

        Plik ten służy pilotom do weryfikacji poprawności naliczeń (np. czy lot
        został policzony jako szkolny czy samodzielny) oraz jako podstawa do rozliczeń księgowych.

        **Bezpieczeństwo:**

        Zwykły pilot może pobrać TYLKO swoje operacje (`WHERE id_pilot = :p_id`).
        Próba manipulacji ID w zapytaniu jest niemożliwa dzięki pobieraniu ID z bezpiecznej sesji (`current_user`).
    """
    security_logger.warning("EXPORT_FINANCIAL_RECORDS", extra={
        'event': 'DATA_EXPORT_FINANCIAL',
        'user': current_user.login,
        'src_ip': request.remote_addr,
        'admin_mode': current_user.rola == 'admin'
    })

    query_params = {'p_id': current_user.id_pilot}

    if current_user.rola == 'admin':
        sql = text("""
                   SELECT r.*, d.pilot_1, d.pilot_2
                   FROM pdt_rpt.v_rozliczenie_finansowe r
                            JOIN pdt_rpt.v_dziennik_lotow d USING (id_lot)
                   WHERE r.kwota_do_zaplaty > 0
                     AND r.deleted_at IS NULL
                   ORDER BY r.id_lot DESC
                   """)
        res = db.session.execute(sql).fetchall()
        header = ['ID Lotu', 'Imię Płatnika', 'Nazwisko Płatnika', 'Rola', 'Cena Total', 'Część płatnika']
    else:
        sql = text("""
                   SELECT r.*, d.pilot_1, d.pilot_2
                   FROM pdt_rpt.v_rozliczenie_finansowe r
                            JOIN pdt_rpt.v_dziennik_lotow d USING (id_lot)
                   WHERE r.kwota_do_zaplaty > 0
                     AND r.id_pilot = :p_id
                     AND r.deleted_at IS NULL
                   ORDER BY r.id_lot DESC
                   """)
        res = db.session.execute(sql, query_params).fetchall()
        header = ['ID Lotu', 'Pilot 1', 'Pilot 2', 'Twoja Rola', 'Cena Total', 'Twoja część']

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(header)

    for f in res:
        cena_t = f"{f.cena_lotu_total:.2f}".replace('.', ',')
        kwota_z = f"{f.kwota_do_zaplaty:.2f}".replace('.', ',')

        if current_user.rola == 'admin':
            writer.writerow([f.id_lot, f.imie, f.nazwisko, f.rola, cena_t, kwota_z])
        else:
            writer.writerow([f.id_lot, f.pilot_1 or "---", f.pilot_2 or "---", f.rola, cena_t, kwota_z])

    return generate_csv_response(output, "rozliczenie_szczegolowe.csv")


@reports_bp.route('/raporty/export/szybowce')
@login_required
def export_szybowce_csv():
    """
        Raport wykorzystania floty (Asset Utilization).

        Generuje statystykę, które szybowce latają najwięcej.
        Dane te są kluczowe dla Zarządu przy podejmowaniu decyzji o zakupie nowych
        szybowców lub sprzedaży tych najmniej używanych (nierentownych).

        Returns:
            Response: Plik `nalot_szybowcow.csv`.
    """
    app_logger.info("EXPORT_AIRCRAFT_STATS", extra={
        'event': 'DATA_EXPORT',
        'user': current_user.login,
        'src_ip': request.remote_addr,
        'report_type': 'AIRCRAFT_UTILIZATION'
    })

    sql = text("SELECT * FROM pdt_core.v_szybowiec_nalot ORDER BY CAST(nalot_calk_h AS FLOAT) DESC")
    res = db.session.execute(sql).fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Znak rej.', 'Typ', 'Suma nalotu (h)'])

    for s in res:
        nalot_c = f"{s.nalot_calk_h:.2f}".replace('.', ',')
        writer.writerow([s.znak_rej, s.typ, nalot_c])

    return generate_csv_response(output, "nalot_szybowcow.csv")


@reports_bp.route('/raporty/export/saldo')
@login_required
def export_saldo_csv():
    """
        Zestawienie sald finansowych (Financial Snapshot).

        Eksportuje aktualny stan kont użytkowników (Wpłaty - Koszty Lotów).

        **Dla Admina:** Służy do szybkiej identyfikacji dłużników (kto jest "na minusie").
        **Dla Pilota:** Służy jako potwierdzenie salda na dzień dzisiejszy.

        Opiera się na widoku `pdt_rpt.v_saldo_pilota`, który gwarantuje, że saldo w CSV
        jest identyczne z tym wyświetlanym na stronie (Single Source of Truth).
    """
    security_logger.info("EXPORT_USER_BALANCES", extra={
        'event': 'DATA_EXPORT_FINANCIAL',
        'user': current_user.login,
        'src_ip': request.remote_addr,
        'target_scope': 'ALL' if current_user.rola == 'admin' else 'SELF'
    })

    if current_user.rola == 'admin':
        sql = text("SELECT * FROM pdt_rpt.v_saldo_pilota ORDER BY saldo ASC")
        res = db.session.execute(sql).fetchall()
    else:
        sql = text("SELECT * FROM pdt_rpt.v_saldo_pilota WHERE id_pilot = :p_id")
        res = db.session.execute(sql, {'p_id': current_user.id_pilot}).fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Imię', 'Nazwisko', 'Suma lotów (koszt)', 'Suma wpłat', 'Saldo końcowe'])

    for s in res:
        s_koszt = f"{s.suma_kosztow:.2f}".replace('.', ',')
        s_wplat = f"{s.suma_wplat:.2f}".replace('.', ',')
        s_saldo = f"{s.saldo:.2f}".replace('.', ',')
        writer.writerow([s.imie, s.nazwisko, s_koszt, s_wplat, s_saldo])

    return generate_csv_response(output, "saldo_pilota.csv")


def generate_csv_response(output, filename):
    """
        Uniwersalny generator odpowiedzi HTTP dla plików CSV.

        Funkcja pomocnicza (Utility), która standaryzuje sposób wysyłania plików do przeglądarki.

        **Szczegóły Techniczne:**

        1.  **Kodowanie UTF-8-SIG:** Dodaje na początku pliku niewidoczny znak BOM (Byte Order Mark).
            Jest to "hack" konieczny dla programu Microsoft Excel, aby poprawnie wyświetlał
            polskie znaki (ą, ę, ś, ć). Bez tego Excel otwierałby pliki jako "krzaczki".
        2.  **Nagłówki MIME:** Ustawia `Content-Disposition: attachment`, co wymusza na przeglądarce
            okno zapisu pliku zamiast próby wyświetlenia tekstu w oknie.

        Args:
            output (io.StringIO): Bufor pamięci z danymi tekstowymi.
            filename (str): Nazwa pliku, którą zobaczy użytkownik.
    """
    output.seek(0)
    return Response(
        output.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )