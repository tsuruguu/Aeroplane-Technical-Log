import json
import hmac
import hashlib
import os
import sys
from dotenv import load_dotenv

load_dotenv()
SECRET_KEY = os.getenv('LOG_SECRET_KEY').encode()


def verify_log_file(file_path):
    """
    Weryfikuje integralność łańcucha logów w podanym pliku JSON.
    """
    if not SECRET_KEY:
        print("BŁĄD: Brak LOG_SECRET_KEY w środowisku!")
        return False

    if not os.path.exists(file_path):
        print(f"BŁĄD: Plik {file_path} nie istnieje.")
        return False

    print(f"--- Weryfikacja pliku: {file_path} ---")

    expected_prev_hash = "0" * 64
    line_number = 0
    tampered = False

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line_number += 1
            try:
                log_record = json.loads(line.strip())
            except json.JSONDecodeError:
                print(f"[LINIA {line_number}] Błąd formatu JSON!")
                tampered = True
                continue

            if log_record.get('prev_signature') != expected_prev_hash:
                print(f"[LINIA {line_number}] PRZERWANY ŁAŃCUCH: prev_signature nie zgadza się z poprzednikiem!")
                tampered = True

            payload = f"{log_record['prev_signature']}|{log_record['timestamp']}|{log_record['level']}|{log_record.get('message', '')}"

            computed_hash = hmac.new(
                SECRET_KEY,
                msg=payload.encode('utf-8'),
                digestmod=hashlib.sha256
            ).hexdigest()

            if log_record.get('signature') != computed_hash:
                print(f"[LINIA {line_number}] MANIPULACJA DANYMI: Podpis cyfrowy jest nieprawidłowy!")
                tampered = True

            expected_prev_hash = log_record.get('signature')

    if not tampered:
        print(f"SUKCES: Integralność pliku potwierdzona. Przeanalizowano {line_number} linii.")
        return True
    else:
        print(f"ALARM: Wykryto manipulację w {file_path}!")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        verify_log_file(sys.argv[1])
    else:
        files_to_check = ["logs/security.log", "logs/application.log", "logs/error.log"]
        for log_file in files_to_check:
            if os.path.exists(log_file):
                verify_audit = verify_log_file(log_file)
                print("-" * 40)