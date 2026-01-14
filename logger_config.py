"""
Konfiguracja zaawansowanego systemu logowania strukturyzowanego (JSON).

Ten moduł implementuje mechanizm 'Log Chaining', który tworzy kryptograficzny
łańcuch dowodowy dla wszystkich logów systemowych. Wykorzystuje HMAC-SHA256
do zapewnienia nienaruszalności (Integrity) i niezaprzeczalności (Non-repudiation) wpisów.

Zastosowane standardy:
- Format: JSON (łatwa integracja z SIEM/Wazuh).
- Kryptografia: HMAC-SHA256 z soleniem poprzednim podpisem.
- Separacja: Podział na kanały access, application, security, error.
"""

import logging
import hmac
import hashlib
import os
from datetime import datetime
from pythonjsonlogger import jsonlogger


LOG_SECRET_KEY = os.getenv('LOG_SECRET_KEY').encode()

last_hashes = {
    "security": "0" * 64,
    "application": "0" * 64,
    "error": "0" * 64,
    "access": "0" * 64
}


class ChainedJsonFormatter(jsonlogger.JsonFormatter):
    """
        Formatter JSON implementujący kryptograficzne łańcuchowanie logów.

        Każdy wpis zawiera podpis (signature) wyliczony z treści bieżącego logu
        oraz podpisu poprzedniego wpisu. Uniemożliwia to usunięcie lub zmianę
        linii logu bez wykrycia przerwania ciągłości łańcucha.
        """
    def add_fields(self, log_record, record, message_dict):
        """
                Wzbogaca rekord logu o metadane bezpieczeństwa i podpisy cyfrowe.

                Args:
                    log_record (dict): Słownik danych logu do sformatowania.
                    record (logging.LogRecord): Obiekt rekordu logu z biblioteki standardowej.
                    message_dict (dict): Dodatkowe pola przekazane w parametrze 'extra'.
                """
        super(ChainedJsonFormatter, self).add_fields(log_record, record, message_dict)

        log_record['timestamp'] = datetime.utcnow().isoformat()
        log_record['level'] = record.levelname

        logger_name = record.name if record.name in last_hashes else "application"
        prev_hash = last_hashes[logger_name]

        payload = f"{prev_hash}|{log_record['timestamp']}|{log_record['level']}|{log_record.get('message', '')}"

        new_hash = hmac.new(
            LOG_SECRET_KEY,
            msg=payload.encode('utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()

        log_record['prev_signature'] = prev_hash
        log_record['signature'] = new_hash

        last_hashes[logger_name] = new_hash


def setup_logging():
    """
        Inicjalizuje hierarchię loggerów i konfiguruje handlery plików.

        Tworzy dedykowane pliki dla różnych poziomów bezpieczeństwa:
        - access.log: Ruch sieciowy i próby połączeń.
        - application.log: Logika biznesowa (operacje lotnicze).
        - security.log: Zdarzenia uwierzytelniania i autoryzacji.
        - error.log: Błędy krytyczne systemu.
        """
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    formatter = ChainedJsonFormatter('%(timestamp)s %(level)s %(name)s %(message)s')

    def create_handler(filename, level):
        """Pomocnicza funkcja do tworzenia FileHandlera z formatterem."""
        handler = logging.FileHandler(f"{log_dir}/{filename}")
        handler.setFormatter(formatter)
        handler.setLevel(level)
        return handler

    access_handler = create_handler("access.log", logging.INFO)
    app_handler = create_handler("application.log", logging.INFO)
    security_handler = create_handler("security.log", logging.INFO)
    error_handler = create_handler("error.log", logging.ERROR)


    logging.getLogger("access").addHandler(access_handler)
    logging.getLogger("access").propagate = False

    logging.getLogger("application").addHandler(app_handler)
    logging.getLogger("application").propagate = False

    logging.getLogger("security").addHandler(security_handler)
    logging.getLogger("security").propagate = False

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(error_handler)


setup_logging()

log_sec = logging.getLogger("security")
log_app = logging.getLogger("application")
log_err = logging.getLogger("error")

log_sec.info("User 'pilot_737' logged in successfully", extra={'ip': '192.168.1.10'})
log_app.info("Technical log entry created for Aircraft SP-ABC")
log_err.error("Database connection timeout in module 'EngineStats'")