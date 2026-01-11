"""
Inicjalizacja warstwy danych (SQLAlchemy).

Plik ten zawiera instancję obiektu bazy danych, która jest importowana
przez inne moduły aplikacji w celu wykonywania operacji SQL.

.. warning::
   W nowszej strukturze projektu zaleca się używanie instancji ``db`` z pliku ``extensions.py``,
   aby uniknąć problemów z importami cyklicznymi (Circular Imports).
"""

from flask_sqlalchemy import SQLAlchemy

#: Globalna instancja bazy danych (ORM)
db = SQLAlchemy()