"""Rozszerzenia Flaska tworzone BEZ aplikacji — `init_app()` robi app.py.

Dzieki temu modele (`logistat/models/`) importuja `db` stad, a nie z app.py,
i nie ma cyklicznych importow: app → models → extensions.
"""
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()
