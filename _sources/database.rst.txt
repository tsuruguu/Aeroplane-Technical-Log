Specyfikacja Techniczna Bazy Danych PDT
=======================================

Analiza Przepływu Danych (DFD)
------------------------------
Poniższy diagram przedstawia przepływ informacji pomiędzy użytkownikami a systemem PDT:

.. image:: diagram_dfd.png
   :alt: Diagram DFD poziomu 1
   :align: center

Analiza przepływu danych w systemie PDT wykazuje ścisłą integrację procesów operacyjnych z warstwą walidacyjną, techniczną oraz finansową. Poniżej opisano szczegółową strukturę przepływu informacji w podziale na główne procesy logiczne poziomu 1 widoczne na diagramie DFD:

**1.0 Uwierzytelnianie i Kontrola Dostępu**
Proces ten stanowi bramę wejściową do systemu, determinując zakres dostępnych funkcjonalności.

* **Wejście**: Dane logowania (unikalny login oraz hasło) przekazywane przez użytkownika.
* **Przetwarzanie**: System weryfikuje poświadczenia w magazynie danych D1 (tabela ``uzytkownik``). Sprawdzane są aktywne uprawnienia oraz przypisane role systemowe (Pilot, Admin, Mechanik).
* **Wynik**: Wygenerowanie bezpiecznego tokenu sesji oraz nadanie odpowiedniego kontekstu uprawnień wewnątrz aplikacji.

**2.0 Zarządzanie Operacjami Lotniczymi**
Jest to centralny proces systemu, w którym następuje transformacja danych wprowadzanych przez pilotów w audytowalne rekordy operacyjne.

* **Wejście**: Kompletne dane lotu oraz skład załogi przesyłane przez formularz rejestracji operacji.
* **Przetwarzanie**: To najbardziej krytyczny etap, w którym system sprawdza dostępność sprzętu oraz uruchamia wyzwalacze walidacyjne (triggers):
    * **Walidacja czasu**: Blokada zapisów o nielogicznej chronologii (start po ladowaniu).
    * **Bezpieczeństwo załogi**: Weryfikacja obecności instruktora lub nadzoru z ziemi dla uczniów-pilotów.
    * **Hierarchia**: Wymuszanie obecności dowódcy (PIC) przy obecności drugiego członka załogi.
* **Wynik**: Potwierdzony i trwały zapis operacji lotniczej w głównym dzienniku lotów.

**3.0 Obsługa Techniczna i Serwisowa**
Proces odpowiedzialny za ewidencję zdatności floty oraz dokumentowanie prac serwisowych.

* **Wejście**: Zgłoszenia usterek technicznych od pilotów oraz raporty napraw generowane przez mechaników.
* **Przetwarzanie**: System pobiera aktualną listę problemów z bazy danych, umożliwiając mechanikom ich edycję oraz zarządzanie cyklem życia usterki (statusy: otwarta, w toku, zamknięta).
* **Wynik**: Aktualizacja stanu technicznego floty oraz kompletna dokumentacja wykonanych prac serwisowych.

**4.0 Generowanie Analiz i Rozliczeń**
Końcowy proces agregacji, w którym dane operacyjne są przeliczane na informacje finansowe i statystyczne.

* **Dane**: Pobieranie archiwalnych danych nalotowych, stawek godzinowych za sprzęt oraz kosztów startów z bazy danych.
* **Przetwarzanie**: Wykorzystanie warstwy widoków raportowych (schemat ``pdt_rpt``) do automatycznego obliczania nalotu pilotów oraz podziału kosztów operacji lotniczych.
* **Wynik**: Generowanie spersonalizowanych dzienników lotów, zestawień sald członkowskich oraz zbiorczych raportów finansowych dla administratorów.

Diagram Relacji (ERD)
---------------------
Poniższy diagram przedstawia logiczną strukturę bazy danych, relacje między encjami oraz klucze główne i obce.

.. image:: diagram_erd.png
   :alt: Diagram ERD bazy danych PDT
   :align: center

Schemat pdt_core (Rdzeń Operacyjny)
-----------------------------------

Schemat ``pdt_core`` zawiera wszystkie tabele odpowiedzialne za procesy operacyjne: ewidencję floty, pilotów, logowanie lotów oraz obsługę techniczną.

Słownik Danych i Ograniczenia
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
W systemie zdefiniowano dziedziny danych (typy ENUM), które ograniczają dopuszczalne wartości:

* **pdt_core.status_usterki**:
    * ``otwarta``: Usterka zgłoszona, oczekuje na weryfikację przez mechanika[c.
    * ``w_toku``: Prace serwisowe są w trakcie realizacji.
    * ``zamknieta``: Usterka usunięta, szybowiec dopuszczony do lotu.
* **pdt_core.rola_w_locie**: Określa funkcję załogi: ``PIC`` (Dowódca), ``SIC`` (Drugi pilot), ``UCZEN``, ``INSTRUKTOR``, ``PASAZER``.
* **pdt_auth.rola_uzytkownika**: Poziomy dostępu: ``admin`` (pełny), ``pilot`` (operacyjny), ``mechanik`` (techniczny) .

Tabela: szybowiec
~~~~~~~~~~~~~~~~~

Przechowuje informacje o flocie szybowców dostępnych w organizacji.

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Kolumna
     - Typ
     - Opis
   * - ``id_szybowiec``
     - BIGINT (PK)
     - Unikalny identyfikator szybowca (Serial).
   * - ``typ``
     - VARCHAR(50)
     - Model/typ szybowca (np. SZD-30 Pirat).
   * - ``znak_rej``
     - VARCHAR(16)
     - Unikalny znak rejestracyjny statku powietrznego (UNIQUE).
   * - ``cena_za_h``
     - NUMERIC(10,2)
     - Stawka za godzinę nalotu (nie może być ujemna).
   * - ``created_at``
     - TIMESTAMP
     - Data utworzenia rekordu (DEFAULT: now()).
   * - ``deleted_at``
     - TIMESTAMP
     - Data usunięcia (Soft Delete).

Tabela: pilot
~~~~~~~~~~~~~

Ewidencja osób uprawnionych do wykonywania lotów.

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Kolumna
     - Typ
     - Opis
   * - ``id_pilot``
     - BIGINT (PK)
     - Unikalny identyfikator pilota.
   * - ``imie``
     - VARCHAR(20)
     - Imię pilota.
   * - ``nazwisko``
     - VARCHAR(30)
     - Nazwisko pilota.
   * - ``licencja``
     - VARCHAR(30)
     - Numer licencji (np. SPL).
   * - ``nalot_zewnetrzny``
     - NUMERIC(10,2)
     - Czas lotu przeniesiony z innych dzienników (do obliczeń nalotu całkowitego).
   * - ``pokazywac_dane``
     - BOOLEAN
     - Zgoda na wyświetlanie danych osobowych w raportach publicznych.

Tabela: lot
~~~~~~~~~~~

Główny rejestr operacji lotniczych. Tabela ta posiada wbudowaną logikę walidacji czasu.

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Kolumna
     - Typ
     - Opis
   * - ``id_lot``
     - BIGINT (PK)
     - Unikalny identyfikator operacji.
   * - ``id_szybowiec``
     - BIGINT (FK)
     - Odniesienie do użytego sprzętu.
   * - ``dt_start``
     - TIMESTAMP
     - Data i godzina momentu startu.
   * - ``dt_ladowanie``
     - TIMESTAMP
     - Data i godzina momentu przyziemienia.
   * - ``data_lotu``
     - DATE
     - **Kolumna generowana** automatycznie z ``dt_start``.
   * - ``rodzaj_startu``
     - ENUM
     - Metoda startu: 'wyciagarka', 'samolot', 'grawitacyjny'.
   * - ``id_start``
     - BIGINT (FK)
     - Lotnisko startu.
   * - ``id_ladowanie``
     - BIGINT (FK)
     - Lotnisko lądowania.
   * - ``id_nadzorujacy``
     - BIGINT (FK)
     - Instruktor nadzorujący (wymagany przy lotach samodzielnych uczniów).
   * - ``czy_oplacony``
     - BOOLEAN
     - Status rozliczenia lotu.

Tabela: lot_pilot
~~~~~~~~~~~~~~~~~

Tabela asocjacyjna definiująca załogę konkretnego lotu.

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Kolumna
     - Typ
     - Opis
   * - ``id_lot``
     - BIGINT (PK, FK)
     - Identyfikator lotu.
   * - ``id_pilot``
     - BIGINT (PK, FK)
     - Identyfikator pilota.
   * - ``rola``
     - ENUM
     - Funkcja w kabinie: 'PIC', 'SIC', 'UCZEN', 'INSTRUKTOR', 'PASAZER'.

Tabela: usterka
~~~~~~~~~~~~~~~

Rejestr problemów technicznych zgłaszanych po lotach.

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Kolumna
     - Typ
     - Opis
   * - ``id_usterka``
     - BIGINT (PK)
     - Unikalny numer zgłoszenia.
   * - ``id_szybowiec``
     - BIGINT (FK)
     - Szybowiec, którego dotyczy usterka.
   * - ``opis``
     - VARCHAR(500)
     - Szczegółowy opis uszkodzenia/usterki.
   * - ``status``
     - ENUM
     - Stan zgłoszenia: 'otwarta', 'w_toku', 'zamknieta'.

Tabela: naprawa
~~~~~~~~~~~~~~~

Dokumentacja prac serwisowych wykonanych przez mechaników.

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Kolumna
     - Typ
     - Opis
   * - ``id_naprawa``
     - INTEGER (PK)
     - Numer wpisu serwisowego.
   * - ``id_usterka``
     - INTEGER (FK)
     - Odniesienie do zgłoszonej usterki.
   * - ``id_mechanik``
     - INTEGER (FK)
     - Odniesienie do użytkownika o roli mechanika.
   * - ``opis_prac``
     - TEXT
     - Opis wykonanych czynności naprawczych.

Tabela: przeglad
~~~~~~~~~~~~~~~~

Harmonogram okresowych przeglądów technicznych (np. 50h, roczny).

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Kolumna
     - Typ
     - Opis
   * - ``id_przeglad``
     - BIGINT (PK)
     - Unikalny identyfikator przeglądu.
   * - ``data_przegladu``
     - DATE
     - Data wykonania inspekcji.
   * - ``typ``
     - VARCHAR(30)
     - Rodzaj przeglądu (np. 'Roczny', '50-godzinny').

Tabela: wplata
~~~~~~~~~~~~~~

Ewidencja wpłat na subkonta pilotów.

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Kolumna
     - Typ
     - Opis
   * - ``id_wplata``
     - BIGINT (PK)
     - Unikalny identyfikator wpłaty.
   * - ``id_pilot``
     - BIGINT (FK)
     - Pilot dokonujący wpłaty.
   * - ``kwota``
     - NUMERIC(10,2)
     - Wartość wpłaty.
   * - ``tytul``
     - VARCHAR(100)
     - Tytuł przelewu/wpłaty.

Logika Biznesowa i Automatyzacja (pdt_core)
-------------------------------------------

System PDT wykorzystuje wyzwalacze (triggers) oraz funkcje proceduralne (PL/pgSQL) do zapewnienia integralności danych i wymuszenia przestrzegania procedur lotniczych.

Funkcje Walidacyjne
~~~~~~~~~~~~~~~~~~~

**1. Walidacja Bezpieczeństwa Ucznia (trg_validate_student_safety)**
Funkcja ta jest kluczowym elementem systemu bezpieczeństwa. Monitoruje przypisania pilotów do lotów i reaguje w przypadku wykrycia roli 'UCZEN'.

* **Mechanizm działania**: Jeśli w locie bierze udział uczeń, system sprawdza, czy w kabinie znajduje się instruktor (rola 'INSTRUKTOR') LUB czy w nagłówku lotu wskazano instruktora nadzorującego z ziemi (kolumna ``id_nadzorujacy``).
* **Błąd**: W przypadku braku obu form nadzoru, system rzuca wyjątek: *"NARUSZENIE BEZPIECZEŃSTWA: Lot samodzielny ucznia... WYMAGA wskazania instruktora nadzorującego!"*.

**2. Kontrola Chronologii Lotu (trg_check_czas_lotu)**
Prosta, ale krytyczna funkcja zapobiegająca błędom operatora przy wprowadzaniu danych czasowych.

* **Mechanizm działania**: Sprawdza, czy data i godzina lądowania (``dt_ladowanie``) jest późniejsza niż data i godzina startu (``dt_start``).
* **Błąd**: Próba zapisu lotu o ujemnym czasie trwania skutkuje błędem logicznym.

**3. Weryfikacja Składu Załogi (enforce_sic_requires_pic)**
Zapewnia poprawność hierarchii w kabinie szybowca.

* **Mechanizm działania**: Blokuje dodanie drugiego pilota (rola 'SIC' - Second-in-Command), jeżeli dla danego lotu nie został wcześniej zdefiniowany dowódca (rola 'PIC' - Pilot-in-Command).
* **Błąd**: *"SIC wymaga istnienia PIC dla lotu %"*.

**4. Automatyczna Aktualizacja Znacznika Czasu (update_updated_at_column)**
Funkcja pomocnicza utrzymująca spójność metadanych.

* **Mechanizm działania**: Przy każdej edycji rekordu w tabelach operacyjnych, automatycznie ustawia kolumnę ``updated_at`` na aktualny czas systemowy (``NOW()``).

Wyzwalacze (Triggers)
~~~~~~~~~~~~~~~~~~~~~

Poniższa tabela przedstawia powiązanie powyższych funkcji z konkretnymi tabelami i zdarzeniami:

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - Tabela
     - Nazwa Triggera
     - Wyzwalana Funkcja
   * - ``lot_pilot``
     - ``trg_check_student_safety``
     - ``trg_validate_student_safety()`` (AFTER INSERT/UPDATE)
   * - ``lot``
     - ``trg_validate_flight_time``
     - ``trg_check_czas_lotu()`` (BEFORE INSERT/UPDATE)
   * - ``lot_pilot``
     - ``trg_sic_requires_pic``
     - ``enforce_sic_requires_pic()`` (BEFORE INSERT/UPDATE)
   * - ``lot``
     - ``trg_lot_updated_at``
     - ``update_updated_at_column()`` (BEFORE UPDATE)
   * - ``szybowiec``
     - ``trg_szybowiec_updated_at``
     - ``update_updated_at_column()`` (BEFORE UPDATE)
   * - ``pilot``
     - ``trg_pilot_updated_at``
     - ``update_updated_at_column()`` (BEFORE UPDATE)

Widoki Danych (pdt_core)
------------------------

Widoki w schemacie ``pdt_core`` służą do uproszczenia zapytań aplikacyjnych poprzez ukrycie złożonych złączeń (JOIN) oraz automatyczne filtrowanie rekordów aktywnych.

Widoki Aktywnych Zasobów
~~~~~~~~~~~~~~~~~~~~~~~~

Te widoki automatycznie odfiltrowują rekordy, które zostały oznaczone jako usunięte (kolumna ``deleted_at IS NULL``).

* **v_aktywne_loty**: Zwraca listę wszystkich lotów, które nie zostały usunięte z dziennika.
* **v_aktywne_szybowce**: Zwraca listę dostępnych szybowców, gotowych do planowania operacji.

Widoki Diagnostyczne i Techniczne
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**v_do_naprawy**
Widok dla mechaników, agregujący informacje o usterkach wymagających interwencji.
* **Logika**: Łączy tabele ``usterka``, ``szybowiec`` oraz ``lot``.
* **Filtrowanie**: Wyświetla tylko usterki o statusie innym niż 'zamknieta'.
* **Zastosowanie**: Główna lista zadań dla personelu technicznego.

**v_loty_usterki**
Widok podsumowujący stan techniczny konkretnych operacji lotniczych.
* **Logika**: Grupuje usterki po identyfikatorze lotu (``id_lot``).
* **Kolumny specjalne**:

    * ``ma_usterke``: Zwraca 'TAK' lub 'NIE'.
    * ``opis_usterek``: Agreguje opisy wielu usterek w jeden ciąg znaków (rozdzielony znakiem " | ") przy użyciu funkcji ``string_agg``.

**v_szybowiec_status**
Kompleksowy widok przedstawiający aktualną "metrykę" statku powietrznego.
* **Logika**: Łączy dane o szybowcu z ostatnim wykonanym przeglądem oraz danymi mechanika, który go przeprowadził.
* **Zastosowanie**: Szybki podgląd zdatności do lotu.

Widoki Statystyczne (Naloty)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**v_pilot_nalot**
Oblicza całkowity czas spędzony w powietrzu przez każdego pilota.
* **Algorytm**: Sumuje różnicę czasu między lądowaniem a startem (``dt_ladowanie - dt_start``), przelicza sekundy na godziny i dodaje wartość z kolumny ``nalot_zewnetrzny``.
* **Obsługa NULL**: Wykorzystuje funkcję ``COALESCE``, aby uniknąć błędów obliczeniowych dla nowych pilotów bez nalotu.

**v_szybowiec_nalot**
Oblicza całkowity nalot (tzw. "resurs") każdego szybowca.
* **Logika**: Sumuje czas trwania wszystkich nieusuniętych lotów przypisanych do danej jednostki (``id_szybowiec``).

Widoki Przeglądów
~~~~~~~~~~~~~~~~~

**v_szybowiec_ostatni_przeglad**
Wyszukuje wyłącznie najświeższą datę przeglądu dla każdego szybowca.
* **Technologia**: Wykorzystuje konstrukcję ``DISTINCT ON (id_szybowiec)`` z sortowaniem malejącym po dacie, co gwarantuje pobranie tylko jednego, najnowszego rekordu dla każdej jednostki.

Schemat pdt_auth (Uwierzytelnianie i Uprawnienia)
-------------------------------------------------

Schemat ``pdt_auth`` zarządza dostępem do systemu. Przechowuje dane kont użytkowników, zahaszowane hasła oraz definiuje role, które determinują zakres dostępnych funkcjonalności.

Typy Wyliczeniowe (Custom ENUMs)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

W celu zapewnienia ścisłej kontroli uprawnień zdefiniowano własny typ danych:

* **pdt_auth.rola_uzytkownika**: Określa typ konta w systemie.
    * ``pilot``: Użytkownik powiązany z profilem pilota w ``pdt_core``.
    * ``admin``: Pełne uprawnienia do zarządzania systemem i konfiguracją.
    * ``mechanik``: Dostęp do modułów serwisowych, usterek i przeglądów.

Tabela: uzytkownik
~~~~~~~~~~~~~~~~~~

Główna tabela przechowująca dane dostępowe. Każdy rekord reprezentuje pojedyncze konto z przypisaną rolą.

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Kolumna
     - Typ
     - Opis
   * - ``id_uzytkownik``
     - BIGINT (PK)
     - Unikalny identyfikator użytkownika.
   * - ``login``
     - VARCHAR(20)
     - Unikalna nazwa użytkownika używana do logowania.
   * - ``haslo_hash``
     - VARCHAR(500)
     - Skrót (hash) hasła użytkownika (bezpieczeństwo danych).
   * - ``rola``
     - ENUM
     - Uprawnienia użytkownika (``pdt_auth.rola_uzytkownika``).
   * - ``id_pilot``
     - BIGINT (FK)
     - Opcjonalne powiązanie z tabelą ``pdt_core.pilot``.



Więzy Integralności i Logika (Constraints)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Baza danych na poziomie schematu wymusza poprawność relacji między kontem a profilem pilota:

1. **Weryfikacja Profilu Pilota (chk_rola_pilot_wymaga_id)**:
   Constraint typu ``CHECK`` gwarantuje, że jeżeli użytkownik posiada rolę 'pilot', to kolumna ``id_pilot`` **musi** zawierać odniesienie do rekordu w tabeli pilotów. Użytkownicy o rolach 'admin' lub 'mechanik' nie muszą posiadać takiego powiązania.

2. **Unikalność Powiązań**:
   Na kolumnie ``id_pilot`` założono klucz unikalny (``UNIQUE``), co oznacza, że jeden profil pilota z ``pdt_core`` może być przypisany do maksymalnie jednego konta użytkownika.

3. **Polityka Usuwania (FK Constraints)**:
   Powiązanie z tabelą ``pdt_core.pilot`` jest skonfigurowane jako ``ON DELETE SET NULL``. W przypadku usunięcia rekordu pilota, konto użytkownika pozostaje w systemie, ale traci powiązanie z danymi personalnymi.


Schemat pdt_rpt (Warstwa Raportowa i Finansowa)
-----------------------------------------------

Schemat ``pdt_rpt`` stanowi warstwę abstrakcji nad danymi surowymi. Zawiera logikę biznesową dotyczącą naliczania opłat, rozliczeń między pilotami oraz generowania zestawień statystycznych.

Widoki Finansowe i Kalkulacyjne
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**v_koszt_lotu**
Dynamicznie oblicza całkowity koszt operacji lotniczej.

* **Algorytm kosztu**:
  Koszt jest sumą trzech składników:

  .. math::
     K_{calkowity} = (T_{h} \times C_{h}) + K_{startu} + K_{dodatkowy}

* **Składniki kosztu**:
    * **Nalot**: Czas lotu (:math:`T_{h}`) mnożony przez stawkę godzinową szybowca (:math:`C_{h}`).
    * **Typ startu**: Wyciągarka (20.00 PLN), Samolot (100.00 PLN), inne (0.00 PLN).
    * **Opłata pasażerska**: Dodatkowe 100.00 PLN, jeśli w locie uczestniczy pasażer.
* **Płatnik**: Widok automatycznie generuje opis płatnika (np. nazwisko ucznia lub podział 50/50 między pilotów).



**v_rozliczenie_finansowe**
Określa, jaką kwotę konkretny pilot winien jest za dany lot, uwzględniając jego rolę.

* **Logika podziału kosztów**:
    * **Uczeń / Pasażer**: Pokrywa 100% kosztów lotu.
    * **Instruktor**: Koszt 0.00 PLN (loty szkolne opłaca uczeń).
    * **PIC (Dowódca)**: 100% kosztów, chyba że leci z pasażerem (wtedy 0.00, bo płaci pasażer) lub drugim pilotem (SIC).
    * **PIC / SIC**: Jeśli w locie bierze udział dwóch pilotów z licencjami, koszt dzielony jest po 50%.

**v_historia_finansowa**
Generuje wyciąg z konta pilota z wykorzystaniem funkcji okna.

* **Funkcja okna (Window Function)**: Oblicza saldo kroczące (saldo po każdej operacji) za pomocą ``SUM(wplyw) OVER (PARTITION BY id_pilot ORDER BY data_operacji)``.
* **Źródła danych**: Łączy wpłaty (wartości dodatnie) oraz naliczone koszty lotów (wartości ujemne).

**v_saldo_pilota**
Podsumowanie aktualnego stanu finansowego wszystkich aktywnych pilotów.

* **Kolumny**: Suma wszystkich wpłat, suma wszystkich kosztów oraz końcowe saldo (suma wpłat - suma kosztów).

Dzienniki i Raporty Operacyjne
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**v_dziennik_lotow**
Kompleksowe zestawienie wszystkich danych o locie w jednym widoku.

* **Dane scalone**: Łączy informacje o szybowcu, czasach, lotniskach startu/lądowania, załodze (imię, nazwisko, licencja) oraz ewentualnych usterkach.
* **Zastosowanie**: Główny widok do eksportu papierowej książki lotów lotniska.

**v_nalot_szybowiec_miesiac**
Statystyka wykorzystania floty w ujęciu kalendarzowym.

* **Grupowanie**: Agreguje sumę godzin nalotu dla każdego szybowca z podziałem na miesiące.

**v_piloci_z_nalotem_min**
Filtr bezpieczeństwa i aktywności.

* **Kryterium**: Wyświetla tylko tych pilotów, których suma nalotu w systemie wynosi co najmniej 5 godzin (klauzula ``HAVING``).

**v_usterki_otwarte**
Raport o gotowości floty.

* **Logika**: Zlicza liczbę aktywnych (niezamkniętych) usterek dla każdego znaku rejestracyjnego.

Analiza Normalizacji i Zależności Funkcyjnych
---------------------------------------------

Struktura bazy danych została poddana procesowi dekompozycji w celu osiągnięcia **Trzeciej Postaci Normalnej (3NF)**:

1. **Pierwsza Postać Normalna (1NF)**: Wszystkie atrybuty w tabelach są atomowe (np. rozdzielenie imienia i nazwiska pilota, brak list wartości w jednej komórce) .
2. **Druga Postać Normalna (2NF)**: Wszystkie kolumny niekluczowe są w pełni zależne funkcyjnie od całego klucza głównego. W tabeli asocjacyjnej ``lot_pilot`` rola jest zależna od pary (id_lot, id_pilot).
3. **Trzecia Postać Normalna (3NF)**: Wyeliminowano zależności przechodnie. Dane o szybowcu (znak rejestracyjny, typ) nie są powielane w tabeli lotów – lot przechowuje jedynie klucz obcy ``id_szybowiec``.

**Eliminacja relacji wiele-do-wielu (n-m)**:
Relacja między Pilotami a Lotami została rozwiązana za pomocą tabeli łączącej ``lot_pilot``, co pozwala na przypisanie wielu osób do jednego lotu (np. uczeń i instruktor) oraz wielu lotów do jednego pilota.


