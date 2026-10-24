"""Akcje - Displays (kafelek od 2026-10-24): nowy modul, na razie pusty ekran."""
from flask import Blueprint, render_template

from logistat.web.wspolne import leader_required

bp = Blueprint('displays', __name__)


@bp.route('/displays')
@leader_required
def displays():
    return render_template('displays.html')
