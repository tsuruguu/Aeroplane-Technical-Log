"""
Modele bazy danych (ORM).

Definiują strukturę tabel w bazie danych PostgreSQL oraz relacje między nimi.
Wykorzystywane są schematy:
- `pdt_core`: Główne dane operacyjne (Piloci, Szybowce, Loty).
- `pdt_auth`: Dane uwierzytelniania (Użytkownicy, Hasła).
- `pdt_rpt`: Widoki raportowe (definiowane w SQL, tutaj mapowane tylko w razie potrzeby).
"""

from extensions import db
from flask_login import UserMixin

class Lotnisko(db.Model):
    """
    Reprezentuje lotnisko lub lądowisko.
    """
    __tablename__ = 'lotnisko'
    __table_args__ = {'schema': 'pdt_core'}

    id_lotnisko = db.Column(db.Integer, primary_key=True)
    #: Pełna nazwa lotniska (np. 'EPPR - Przasnysz')
    nazwa = db.Column(db.String(50), nullable=False)
    #: Kod ICAO lub inny identyfikator (np. 'EPPR')
    kod = db.Column(db.String(10))
    #: Miasto lokalizacji
    miasto = db.Column(db.String(50))

class Szybowiec(db.Model):
    """
    Reprezentuje statek powietrzny (szybowiec).
    """
    __tablename__ = 'szybowiec'
    __table_args__ = {'schema': 'pdt_core'}

    id_szybowiec = db.Column(db.Integer, primary_key=True)
    #: Model szybowca (np. 'SZD-30 Pirat')
    typ = db.Column(db.String(50), nullable=False)
    #: Znaki rejestracyjne (np. 'SP-1234')
    znak_rej = db.Column(db.String(10), unique=True, nullable=False)
    #: Stawka godzinowa za wynajem
    cena_za_h = db.Column(db.Numeric(10, 2))

class Pilot(db.Model):
    """
    Reprezentuje osobę fizyczną (Pilota, Ucznia, Instruktora).
    """
    __tablename__ = 'pilot'
    __table_args__ = {'schema': 'pdt_core'}

    id_pilot = db.Column(db.Integer, primary_key=True)
    #: Imię pilota
    imie = db.Column(db.String(50), nullable=False)
    #: Nazwisko pilota
    nazwisko = db.Column(db.String(50), nullable=False)
    #: Numer licencji lub status (np. 'UCZEŃ')
    licencja = db.Column(db.String(50))
    #: Zgoda RODO na wyświetlanie nazwiska w rankingach
    pokazywac_dane = db.Column(db.Boolean, default=False)
    #: Zgoda RODO na publiczny numer licencji
    pokazywac_licencje = db.Column(db.Boolean, default=False)
    #: Ilość godzin wylatana poza tym systemem (do bilansu total)
    nalot_zewnetrzny = db.Column(db.Numeric(10, 2), default=0.00)
    #: Data usunięcia (Soft Delete). Jeśli NULL, pilot jest aktywny.
    deleted_at = db.Column(db.DateTime, nullable=True)

class Uzytkownik(UserMixin, db.Model):
    """
    Reprezentuje konto systemowe do logowania.

    Model tożsamości cyfrowej w schemacie `pdt_auth`.
    Odpowiada za mechanizmy uwierzytelniania, przechowuje hasze haseł
    i mapuje użytkowników na role systemowe oraz profile osobowe (1:1).
    """
    __tablename__ = 'uzytkownik'
    __table_args__ = {'schema': 'pdt_auth'}

    id_uzytkownik = db.Column(db.Integer, primary_key=True)
    #: Unikalny login użytkownika
    login = db.Column(db.String(20), unique=True, nullable=False)
    #: Zahaszowane hasło (scrypt/pbkdf2)
    haslo_hash = db.Column(db.String(200), nullable=False)
    #: Uprawnienia ('admin', 'mechanik', 'pilot')
    rola = db.Column(db.String(20), nullable=False)
    #: Klucz obcy do tabeli `pdt_core.pilot`
    id_pilot = db.Column(db.Integer, db.ForeignKey('pdt_core.pilot.id_pilot'), unique=True)

    def get_id(self):
        """Metoda wymagana przez Flask-Login."""
        return str(self.id_uzytkownik)