"""Forecast vs Actual: plan sztuk per Loading date, wykresy, autozapis, eksport Excel."""
import io
from datetime import datetime, timedelta

import openpyxl
from flask import Blueprint, jsonify, make_response, render_template, request
from flask_login import current_user
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import func

from logistat.czas import local_today
from logistat.extensions import db
from logistat.models import Forecast, ImportedCarton
from logistat.web.wspolne import leader_required, require_int

bp = Blueprint('forecast', __name__)


@bp.route('/forecast')
@leader_required
def forecast_page():
    today = local_today()
    date_from = (today - timedelta(days=7)).isoformat()
    date_to = (today + timedelta(days=14)).isoformat()
    return render_template('forecast.html', date_from=date_from, date_to=date_to)


@bp.route('/api/forecast/chart-data')
@leader_required
def api_forecast_chart_data():
    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')

    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        date_from = local_today() - timedelta(days=7)

    try:
        date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        date_to = local_today() + timedelta(days=14)

    actual_rows = db.session.query(
        ImportedCarton.data_pliku,
        func.sum(ImportedCarton.stueckzahl).label('total')
    ).filter(
        ImportedCarton.data_pliku >= date_from,
        ImportedCarton.data_pliku <= date_to,
        ImportedCarton.data_pliku.isnot(None)
    ).group_by(ImportedCarton.data_pliku).all()

    actual_map = {row.data_pliku: (row.total or 0) for row in actual_rows}

    forecast_rows = Forecast.query.filter(
        Forecast.date >= date_from,
        Forecast.date <= date_to
    ).all()

    forecast_map = {f.date: {'quantity': f.quantity or 0, 'notes': f.notes or ''} for f in forecast_rows}

    result = []
    current = date_from
    while current <= date_to:
        forecast_qty = forecast_map.get(current, {}).get('quantity', 0)
        actual_qty = actual_map.get(current, 0)
        result.append({
            'date': current.isoformat(),
            'forecast': forecast_qty,
            'actual': actual_qty,
            # Actual − Forecast: przyjechalo mniej niz plan → minus (operacje
            # czytaly odwrotny znak jako nadwyzke).
            'diff': actual_qty - forecast_qty,
            'notes': forecast_map.get(current, {}).get('notes', '')
        })
        current += timedelta(days=1)

    return jsonify(result)


@bp.route('/api/forecast/save', methods=['POST'])
@leader_required
def api_forecast_save():
    data = request.get_json(silent=True)
    entries = data if isinstance(data, list) else [data or {}]

    saved = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        date_str = str(entry.get('date') or '').strip()
        try:
            d = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue

        qty = require_int(entry.get('quantity') or 0, 'quantity')
        notes = (entry.get('notes') or '').strip()

        existing = Forecast.query.filter_by(date=d).first()
        if existing:
            existing.quantity = qty
            existing.notes = notes
            existing.updated_at = datetime.utcnow()
            existing.updated_by = current_user.id
        else:
            db.session.add(Forecast(
                date=d,
                quantity=qty,
                notes=notes,
                created_by=current_user.id
            ))
        saved += 1

    db.session.commit()
    return jsonify({'message': f'Zapisano {saved} wpisów.', 'saved': saved})


@bp.route('/api/forecast/export')
@leader_required
def api_forecast_export():

    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')

    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        date_from = local_today() - timedelta(days=7)

    try:
        date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        date_to = local_today() + timedelta(days=14)

    actual_rows = db.session.query(
        ImportedCarton.data_pliku,
        func.sum(ImportedCarton.stueckzahl).label('total')
    ).filter(
        ImportedCarton.data_pliku >= date_from,
        ImportedCarton.data_pliku <= date_to,
        ImportedCarton.data_pliku.isnot(None)
    ).group_by(ImportedCarton.data_pliku).all()

    actual_map = {row.data_pliku: (row.total or 0) for row in actual_rows}

    forecast_rows = Forecast.query.filter(
        Forecast.date >= date_from,
        Forecast.date <= date_to
    ).all()

    forecast_map = {f.date: {'quantity': f.quantity or 0, 'notes': f.notes or ''} for f in forecast_rows}

    days = []
    current = date_from
    while current <= date_to:
        days.append(current)
        current += timedelta(days=1)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Forecast vs Actual'

    header_font = Font(bold=True, color='FFFFFF')
    col_fills = [
        PatternFill('solid', fgColor='2D3250'),
        PatternFill('solid', fgColor='4A6FD9'),
        PatternFill('solid', fgColor='27AE60'),
        PatternFill('solid', fgColor='C0392B'),
        PatternFill('solid', fgColor='7D3C98'),
    ]
    headers = ['Data', 'Forecast', 'Actual (Sztuki)', 'Różnica (A-F)', 'Notatki']

    for col, (h, fill) in enumerate(zip(headers, col_fills), start=1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = fill
        cell.alignment = Alignment(horizontal='center')

    for row_idx, d in enumerate(days, start=2):
        forecast_qty = forecast_map.get(d, {}).get('quantity', 0)
        actual_qty = actual_map.get(d, 0)
        diff = actual_qty - forecast_qty

        ws.cell(row=row_idx, column=1, value=d.strftime('%d.%m.%Y'))
        ws.cell(row=row_idx, column=2, value=forecast_qty)
        ws.cell(row=row_idx, column=3, value=actual_qty)
        diff_cell = ws.cell(row=row_idx, column=4, value=diff)
        ws.cell(row=row_idx, column=5, value=forecast_map.get(d, {}).get('notes', ''))

        if diff > 0:
            diff_cell.fill = PatternFill('solid', fgColor='FDEBD0')
        elif diff < 0:
            diff_cell.fill = PatternFill('solid', fgColor='FADBD8')

    for col_letter, width in [('A', 14), ('B', 14), ('C', 18), ('D', 18), ('E', 35)]:
        ws.column_dimensions[col_letter].width = width

    n = len(days)
    if n > 0:
        chart = BarChart()
        chart.type = 'col'
        chart.grouping = 'clustered'
        chart.title = 'Forecast vs Actual'
        chart.y_axis.title = 'Ilość paczek'
        chart.x_axis.title = 'Data'
        chart.width = 26
        chart.height = 14

        forecast_ref = Reference(ws, min_col=2, min_row=1, max_row=n + 1)
        actual_ref = Reference(ws, min_col=3, min_row=1, max_row=n + 1)
        dates_ref = Reference(ws, min_col=1, min_row=2, max_row=n + 1)

        chart.add_data(forecast_ref, titles_from_data=True)
        chart.add_data(actual_ref, titles_from_data=True)
        chart.set_categories(dates_ref)
        chart.series[0].graphicalProperties.solidFill = '4A6FD9'
        chart.series[1].graphicalProperties.solidFill = '27AE60'

        ws.add_chart(chart, 'G2')

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    resp = make_response(buf.read())
    resp.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    resp.headers['Content-Disposition'] = (
        f'attachment; filename=forecast_{date_from_str}_{date_to_str}.xlsx'
    )
    return resp
