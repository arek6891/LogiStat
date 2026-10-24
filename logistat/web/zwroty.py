"""Zwroty (kafelek od 2026-10-24): nowy modul, na razie pusty ekran."""
from flask import Blueprint, render_template

from logistat.web.wspolne import leader_required

bp = Blueprint('zwroty', __name__)


@bp.route('/zwroty')
@leader_required
def zwroty():
    return render_template('zwroty.html')
