import os
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, and_

# ── App Config ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'logistat-dev-key-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///logistat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ══════════════════════════════════════════════════════════════════════════════
#  MODELS
# ══════════════════════════════════════════════════════════════════════════════

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(150), nullable=False)
    barcode_id = db.Column(db.String(100), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=True)  # only leaders/admins
    role = db.Column(db.String(20), default='operator')  # operator | leader | admin
    is_active_user = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'display_name': self.display_name,
            'barcode_id': self.barcode_id,
            'role': self.role,
            'is_active_user': self.is_active_user
        }


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sort_order': self.sort_order,
            'is_active': self.is_active
        }


class Shift(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    shift_number = db.Column(db.Integer, nullable=False)  # 1 or 2
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('date', 'shift_number', name='uq_shift_date_number'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'shift_number': self.shift_number
        }


class ShiftAttendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow)

    shift = db.relationship('Shift', backref=db.backref('attendances', lazy=True))
    user = db.relationship('User', backref=db.backref('attendances', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('shift_id', 'user_id', name='uq_attendance_shift_user'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'shift_id': self.shift_id,
            'user_id': self.user_id,
            'user': self.user.to_dict(),
            'scanned_at': self.scanned_at.isoformat()
        }


class ActivityAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)
    is_suggestion = db.Column(db.Boolean, default=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

    shift = db.relationship('Shift', backref=db.backref('assignments', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('assignments', lazy=True))
    activity = db.relationship('Activity', backref=db.backref('assignments', lazy=True))
    assigner = db.relationship('User', foreign_keys=[assigned_by])

    def to_dict(self):
        return {
            'id': self.id,
            'shift_id': self.shift_id,
            'user_id': self.user_id,
            'activity_id': self.activity_id,
            'is_suggestion': self.is_suggestion,
            'user': self.user.to_dict(),
            'activity': self.activity.to_dict()
        }


class DailyStat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    note = db.Column(db.String(300), nullable=True)

    # Audit fields
    entered_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    entered_at = db.Column(db.DateTime, default=datetime.utcnow)
    modified_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    modified_at = db.Column(db.DateTime, nullable=True)

    shift = db.relationship('Shift', backref=db.backref('stats', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id],
                           backref=db.backref('stats', lazy=True))
    activity = db.relationship('Activity', backref=db.backref('stats', lazy=True))
    entered_by_user = db.relationship('User', foreign_keys=[entered_by])
    modified_by_user = db.relationship('User', foreign_keys=[modified_by])

    __table_args__ = (
        db.UniqueConstraint('shift_id', 'user_id', 'activity_id',
                            name='uq_stat_shift_user_activity'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'shift_id': self.shift_id,
            'user_id': self.user_id,
            'activity_id': self.activity_id,
            'quantity': self.quantity,
            'note': self.note,
            'entered_by': self.entered_by,
            'entered_at': self.entered_at.isoformat() if self.entered_at else None,
            'modified_by': self.modified_by,
            'modified_at': self.modified_at.isoformat() if self.modified_at else None,
            'user': self.user.to_dict(),
            'activity': self.activity.to_dict()
        }


class CountryMapping(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(150), nullable=False)
    innenauftrag = db.Column(db.String(100), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'country': self.country,
            'innenauftrag': self.innenauftrag
        }


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def leader_required(f):
    """Decorator: requires leader or admin role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role not in ('leader', 'admin'):
            flash('Brak uprawnień.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator: requires admin role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != 'admin':
            flash('Brak uprawnień.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


# ══════════════════════════════════════════════════════════════════════════════
#  HELPER: get or create shift
# ══════════════════════════════════════════════════════════════════════════════

def get_or_create_shift(shift_date, shift_number):
    """Get existing shift or create new one."""
    shift = Shift.query.filter_by(date=shift_date, shift_number=shift_number).first()
    if not shift:
        shift = Shift(date=shift_date, shift_number=shift_number)
        db.session.add(shift)
        db.session.commit()
    return shift


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('scanner', shift_number=1))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.role in ('leader', 'admin') and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('Nieprawidłowy login lub hasło.', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/scanner/<int:shift_number>')
@leader_required
def scanner(shift_number):
    if shift_number not in (1, 2):
        shift_number = 1
    today = date.today()
    shift = get_or_create_shift(today, shift_number)
    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id)\
        .order_by(ShiftAttendance.scanned_at.desc()).all()
    return render_template('scanner.html',
                           shift_number=shift_number,
                           shift=shift,
                           attendances=attendances,
                           today=today)


@app.route('/assignment')
@leader_required
def assignment():
    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    return render_template('assignment.html', activities=activities)


@app.route('/data-entry')
@leader_required
def data_entry():
    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    return render_template('data_entry.html', activities=activities)


@app.route('/stats')
@leader_required
def stats():
    users = User.query.filter_by(is_active_user=True)\
        .order_by(User.display_name).all()
    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()
    return render_template('stats.html', users=users, activities=activities)


@app.route('/admin/activities')
@admin_required
def admin_activities():
    activities = Activity.query.order_by(Activity.sort_order).all()
    return render_template('admin_activities.html', activities=activities)


@app.route('/admin/users')
@leader_required
def admin_users():
    users = User.query.order_by(User.display_name).all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/panel')
@admin_required
def admin_panel():
    return render_template('admin_panel.html')


@app.route('/admin/country-mapping')
@admin_required
def admin_country_mapping():
    mappings = CountryMapping.query.order_by(CountryMapping.country).all()
    return render_template('admin_country_mapping.html', mappings=mappings)


# ══════════════════════════════════════════════════════════════════════════════
#  API: BARCODE SCANNING
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/scan', methods=['POST'])
@leader_required
def api_scan():
    data = request.get_json()
    barcode = data.get('barcode', '').strip()
    shift_number = data.get('shift_number', 1)
    scan_date = data.get('date', date.today().isoformat())

    if not barcode:
        return jsonify({'error': 'Brak kodu kreskowego.'}), 400

    # Look up user by barcode
    user = User.query.filter_by(barcode_id=barcode, is_active_user=True).first()
    if not user:
        return jsonify({
            'error': 'Nieznany kod kreskowy! Dodaj użytkownika w panelu.'
        }), 404

    # Get or create shift
    shift_date = date.fromisoformat(scan_date)
    shift = get_or_create_shift(shift_date, shift_number)

    # Check if already scanned
    existing = ShiftAttendance.query.filter_by(
        shift_id=shift.id, user_id=user.id
    ).first()
    if existing:
        return jsonify({
            'warning': f'{user.display_name} już zarejestrowany/a na zmianę {shift_number}.',
            'user': user.to_dict(),
            'already_scanned': True
        }), 200

    # Register attendance
    attendance = ShiftAttendance(shift_id=shift.id, user_id=user.id)
    db.session.add(attendance)
    db.session.commit()

    return jsonify({
        'message': f'{user.display_name} zarejestrowany/a na zmianę {shift_number}.',
        'user': user.to_dict(),
        'attendance': attendance.to_dict()
    }), 201


@app.route('/api/scan/<int:attendance_id>', methods=['DELETE'])
@leader_required
def api_unscan(attendance_id):
    attendance = ShiftAttendance.query.get_or_404(attendance_id)
    db.session.delete(attendance)
    db.session.commit()
    return jsonify({'message': 'Usunięto rejestrację.'}), 200


@app.route('/api/shift/attendances', methods=['GET'])
@leader_required
def api_shift_attendances():
    shift_date = request.args.get('date', date.today().isoformat())
    shift_number = int(request.args.get('shift_number', 1))
    shift = Shift.query.filter_by(
        date=date.fromisoformat(shift_date),
        shift_number=shift_number
    ).first()
    if not shift:
        return jsonify({'attendances': [], 'shift': None}), 200
    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id)\
        .order_by(ShiftAttendance.scanned_at.desc()).all()
    return jsonify({
        'attendances': [a.to_dict() for a in attendances],
        'shift': shift.to_dict()
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: ASSIGNMENT (DRAG & DROP)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/assignment/data', methods=['GET'])
@leader_required
def api_assignment_data():
    """Get all assignment data for a given date and shift."""
    shift_date = request.args.get('date', date.today().isoformat())
    shift_number = int(request.args.get('shift_number', 1))

    shift = Shift.query.filter_by(
        date=date.fromisoformat(shift_date),
        shift_number=shift_number
    ).first()

    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()

    if not shift:
        return jsonify({
            'shift': None,
            'attendees': [],
            'assignments': [],
            'activities': [a.to_dict() for a in activities]
        }), 200

    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id).all()
    assignments = ActivityAssignment.query.filter_by(shift_id=shift.id).all()

    # Build set of already-assigned user IDs
    assigned_user_ids = {a.user_id for a in assignments}

    return jsonify({
        'shift': shift.to_dict(),
        'attendees': [a.user.to_dict() for a in attendances],
        'assignments': [a.to_dict() for a in assignments],
        'activities': [a.to_dict() for a in activities],
        'unassigned': [a.user.to_dict() for a in attendances
                       if a.user_id not in assigned_user_ids]
    }), 200


@app.route('/api/assignment/suggestions', methods=['GET'])
@leader_required
def api_assignment_suggestions():
    """Generate AI-based assignment suggestions based on user statistics."""
    shift_date = request.args.get('date', date.today().isoformat())
    shift_number = int(request.args.get('shift_number', 1))

    shift = Shift.query.filter_by(
        date=date.fromisoformat(shift_date),
        shift_number=shift_number
    ).first()
    if not shift:
        return jsonify({'suggestions': []}), 200

    attendances = ShiftAttendance.query.filter_by(shift_id=shift.id).all()
    attendee_ids = [a.user_id for a in attendances]
    if not attendee_ids:
        return jsonify({'suggestions': []}), 200

    activities = Activity.query.filter_by(is_active=True)\
        .order_by(Activity.sort_order).all()

    # Calculate average quantity per user per activity (last 30 days)
    thirty_days_ago = date.fromisoformat(shift_date) - timedelta(days=30)
    stats = db.session.query(
        DailyStat.user_id,
        DailyStat.activity_id,
        func.avg(DailyStat.quantity).label('avg_qty'),
        func.count(DailyStat.id).label('days_worked')
    ).join(Shift).filter(
        DailyStat.user_id.in_(attendee_ids),
        Shift.date >= thirty_days_ago
    ).group_by(DailyStat.user_id, DailyStat.activity_id).all()

    # Build performance map: {(user_id, activity_id): avg_qty}
    perf = {}
    for s in stats:
        perf[(s.user_id, s.activity_id)] = float(s.avg_qty)

    # Greedy assignment: for each activity, pick the best unassigned user
    suggestions = []
    assigned = set()

    # Sort activities by fewest qualified workers first
    activity_scores = []
    for act in activities:
        qualified = sum(1 for uid in attendee_ids
                       if perf.get((uid, act.id), 0) > 0)
        activity_scores.append((qualified, act))
    activity_scores.sort(key=lambda x: x[0])

    for _, act in activity_scores:
        # Rank available users by performance for this activity
        candidates = []
        for uid in attendee_ids:
            if uid not in assigned:
                avg = perf.get((uid, act.id), 0)
                candidates.append((avg, uid))
        candidates.sort(reverse=True)

        if candidates:
            best_avg, best_uid = candidates[0]
            suggestions.append({
                'user_id': best_uid,
                'activity_id': act.id,
                'avg_quantity': best_avg
            })
            assigned.add(best_uid)

    # Assign remaining unassigned users to activities with fewest people
    activity_counts = {act.id: 0 for act in activities}
    for s in suggestions:
        activity_counts[s['activity_id']] = activity_counts.get(s['activity_id'], 0) + 1

    for uid in attendee_ids:
        if uid not in assigned:
            # Find activity with fewest assigned people
            min_act_id = min(activity_counts, key=activity_counts.get)
            suggestions.append({
                'user_id': uid,
                'activity_id': min_act_id,
                'avg_quantity': 0
            })
            activity_counts[min_act_id] += 1
            assigned.add(uid)

    return jsonify({'suggestions': suggestions}), 200


@app.route('/api/assignment/save', methods=['POST'])
@leader_required
def api_assignment_save():
    """Save drag & drop assignments."""
    data = request.get_json()
    shift_date = data.get('date', date.today().isoformat())
    shift_number = data.get('shift_number', 1)
    assignments = data.get('assignments', [])

    shift = get_or_create_shift(date.fromisoformat(shift_date), shift_number)

    # Clear existing assignments for this shift
    ActivityAssignment.query.filter_by(shift_id=shift.id).delete()

    for a in assignments:
        assignment = ActivityAssignment(
            shift_id=shift.id,
            user_id=a['user_id'],
            activity_id=a['activity_id'],
            is_suggestion=a.get('is_suggestion', False),
            assigned_by=current_user.id
        )
        db.session.add(assignment)

    db.session.commit()
    return jsonify({'message': 'Przydzielenie zapisane.'}), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: DAILY STATS (DATA ENTRY)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/daily-stats', methods=['GET'])
@leader_required
def api_daily_stats_get():
    """Get stats for a given date and shift."""
    shift_date = request.args.get('date', date.today().isoformat())
    shift_number = int(request.args.get('shift_number', 1))

    shift = Shift.query.filter_by(
        date=date.fromisoformat(shift_date),
        shift_number=shift_number
    ).first()
    if not shift:
        return jsonify({'stats': [], 'shift': None}), 200

    # Get assignments for this shift
    assignments = ActivityAssignment.query.filter_by(shift_id=shift.id).all()
    stats = DailyStat.query.filter_by(shift_id=shift.id).all()

    return jsonify({
        'shift': shift.to_dict(),
        'assignments': [a.to_dict() for a in assignments],
        'stats': [s.to_dict() for s in stats]
    }), 200


@app.route('/api/daily-stats', methods=['POST'])
@leader_required
def api_daily_stats_save():
    """Save or update daily statistics."""
    data = request.get_json()
    shift_date = data.get('date', date.today().isoformat())
    shift_number = data.get('shift_number', 1)
    entries = data.get('entries', [])

    shift = get_or_create_shift(date.fromisoformat(shift_date), shift_number)

    for entry in entries:
        existing = DailyStat.query.filter_by(
            shift_id=shift.id,
            user_id=entry['user_id'],
            activity_id=entry['activity_id']
        ).first()

        if existing:
            existing.quantity = entry.get('quantity', 0)
            existing.note = entry.get('note', '')
            existing.modified_by = current_user.id
            existing.modified_at = datetime.utcnow()
        else:
            stat = DailyStat(
                shift_id=shift.id,
                user_id=entry['user_id'],
                activity_id=entry['activity_id'],
                quantity=entry.get('quantity', 0),
                note=entry.get('note', ''),
                entered_by=current_user.id
            )
            db.session.add(stat)

    db.session.commit()
    return jsonify({'message': 'Statystyki zapisane.'}), 200


@app.route('/api/daily-stats/<int:stat_id>', methods=['PUT'])
@leader_required
def api_daily_stat_update(stat_id):
    """Update a single daily stat (mistake correction)."""
    stat = DailyStat.query.get_or_404(stat_id)
    data = request.get_json()

    stat.quantity = data.get('quantity', stat.quantity)
    stat.note = data.get('note', stat.note)
    stat.modified_by = current_user.id
    stat.modified_at = datetime.utcnow()

    db.session.commit()
    return jsonify({'message': 'Zaktualizowano.', 'stat': stat.to_dict()}), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: STATISTICS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/stats/user/<int:user_id>', methods=['GET'])
@leader_required
def api_stats_user(user_id):
    """Get per-user statistics, grouped by day and month."""
    user = User.query.get_or_404(user_id)
    activity_id = request.args.get('activity_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    query = db.session.query(
        DailyStat, Shift
    ).join(Shift).filter(DailyStat.user_id == user_id)

    if activity_id:
        query = query.filter(DailyStat.activity_id == activity_id)
    if date_from:
        query = query.filter(Shift.date >= date.fromisoformat(date_from))
    if date_to:
        query = query.filter(Shift.date <= date.fromisoformat(date_to))

    results = query.order_by(Shift.date.desc()).all()

    daily_stats = []
    monthly_agg = {}

    for stat, shift in results:
        daily_stats.append({
            'date': shift.date.isoformat(),
            'shift_number': shift.shift_number,
            'activity': stat.activity.name,
            'activity_id': stat.activity_id,
            'quantity': stat.quantity,
            'note': stat.note,
            'entered_by': stat.entered_by_user.display_name if stat.entered_by_user else None,
            'modified_by': stat.modified_by_user.display_name if stat.modified_by_user else None,
            'modified_at': stat.modified_at.isoformat() if stat.modified_at else None,
            'stat_id': stat.id
        })

        month_key = shift.date.strftime('%Y-%m')
        act_name = stat.activity.name
        key = (month_key, act_name)
        if key not in monthly_agg:
            monthly_agg[key] = {'total': 0, 'days': 0}
        monthly_agg[key]['total'] += stat.quantity
        monthly_agg[key]['days'] += 1

    monthly_stats = [
        {
            'month': k[0],
            'activity': k[1],
            'total_quantity': v['total'],
            'days_worked': v['days'],
            'avg_per_day': round(v['total'] / v['days'], 1) if v['days'] > 0 else 0
        }
        for k, v in sorted(monthly_agg.items(), reverse=True)
    ]

    return jsonify({
        'user': user.to_dict(),
        'daily': daily_stats,
        'monthly': monthly_stats
    }), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: ADMIN — ACTIVITIES
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/activities', methods=['GET'])
@leader_required
def api_activities():
    activities = Activity.query.order_by(Activity.sort_order).all()
    return jsonify([a.to_dict() for a in activities]), 200


@app.route('/api/activities', methods=['POST'])
@admin_required
def api_activity_create():
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Nazwa wymagana.'}), 400

    max_order = db.session.query(func.max(Activity.sort_order)).scalar() or 0
    activity = Activity(name=name, sort_order=max_order + 1)
    db.session.add(activity)
    db.session.commit()
    return jsonify(activity.to_dict()), 201


@app.route('/api/activities/<int:activity_id>', methods=['PUT'])
@admin_required
def api_activity_update(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    data = request.get_json()

    if 'name' in data:
        activity.name = data['name'].strip()
    if 'sort_order' in data:
        activity.sort_order = data['sort_order']
    if 'is_active' in data:
        activity.is_active = data['is_active']

    db.session.commit()
    return jsonify(activity.to_dict()), 200


@app.route('/api/activities/<int:activity_id>', methods=['DELETE'])
@admin_required
def api_activity_delete(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    db.session.delete(activity)
    db.session.commit()
    return jsonify({'message': 'Usunięto.'}), 200


@app.route('/api/activities/reorder', methods=['POST'])
@admin_required
def api_activities_reorder():
    data = request.get_json()
    order = data.get('order', [])
    for i, activity_id in enumerate(order):
        act = Activity.query.get(activity_id)
        if act:
            act.sort_order = i
    db.session.commit()
    return jsonify({'message': 'Kolejność zapisana.'}), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: ADMIN — USERS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/users', methods=['GET'])
@leader_required
def api_users():
    users = User.query.order_by(User.display_name).all()
    return jsonify([u.to_dict() for u in users]), 200


@app.route('/api/users', methods=['POST'])
@leader_required
def api_user_create():
    data = request.get_json()
    username = data.get('username', '').strip()
    display_name = data.get('display_name', '').strip()
    barcode_id = data.get('barcode_id', '').strip()
    role = data.get('role', 'operator')
    password = data.get('password', '')

    if not username or not display_name:
        return jsonify({'error': 'Login i nazwa wyświetlana są wymagane.'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Taki login już istnieje.'}), 400

    if barcode_id and User.query.filter_by(barcode_id=barcode_id).first():
        return jsonify({'error': 'Taki kod kreskowy już istnieje.'}), 400

    user = User(
        username=username,
        display_name=display_name,
        barcode_id=barcode_id or None,
        role=role
    )
    if role in ('leader', 'admin') and password:
        user.set_password(password)

    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@leader_required
def api_user_update(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()

    if 'display_name' in data:
        user.display_name = data['display_name'].strip()
    if 'barcode_id' in data:
        new_barcode = data['barcode_id'].strip()
        if new_barcode:
            existing = User.query.filter(
                User.barcode_id == new_barcode, User.id != user_id
            ).first()
            if existing:
                return jsonify({'error': 'Taki kod kreskowy już istnieje.'}), 400
            user.barcode_id = new_barcode
        else:
            user.barcode_id = None
    if 'role' in data:
        user.role = data['role']
    if 'is_active_user' in data:
        user.is_active_user = data['is_active_user']
    if 'password' in data and data['password']:
        user.set_password(data['password'])

    db.session.commit()
    return jsonify(user.to_dict()), 200


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@leader_required
def api_user_delete(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active_user = False  # soft delete
    db.session.commit()
    return jsonify({'message': 'Dezaktywowano.'}), 200


# ══════════════════════════════════════════════════════════════════════════════
#  API: ADMIN — COUNTRY MAPPINGS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/country-mappings', methods=['GET'])
@admin_required
def api_country_mappings():
    mappings = CountryMapping.query.order_by(CountryMapping.country).all()
    return jsonify([m.to_dict() for m in mappings]), 200


@app.route('/api/country-mappings', methods=['POST'])
@admin_required
def api_country_mapping_create():
    data = request.get_json()
    country = data.get('country', '').strip()
    innenauftrag = data.get('innenauftrag', '').strip()
    if not country or not innenauftrag:
        return jsonify({'error': 'Kraj i Innenauftrag są wymagane.'}), 400

    mapping = CountryMapping(country=country, innenauftrag=innenauftrag)
    db.session.add(mapping)
    db.session.commit()
    return jsonify(mapping.to_dict()), 201


@app.route('/api/country-mappings/<int:mapping_id>', methods=['PUT'])
@admin_required
def api_country_mapping_update(mapping_id):
    mapping = CountryMapping.query.get_or_404(mapping_id)
    data = request.get_json()
    if 'country' in data:
        mapping.country = data['country'].strip()
    if 'innenauftrag' in data:
        mapping.innenauftrag = data['innenauftrag'].strip()
    db.session.commit()
    return jsonify(mapping.to_dict()), 200


@app.route('/api/country-mappings/<int:mapping_id>', methods=['DELETE'])
@admin_required
def api_country_mapping_delete(mapping_id):
    mapping = CountryMapping.query.get_or_404(mapping_id)
    db.session.delete(mapping)
    db.session.commit()
    return jsonify({'message': 'Usunięto mapowanie.'}), 200


# ══════════════════════════════════════════════════════════════════════════════
#  SEED DATA
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_ACTIVITIES = [
    'Post Processing',
    'Zwroty',
    'Organic Decoration',
    'Rollout Decoration',
    'Expansion',
    'Textile-Picking',
    'Order-VAS',
    'Carton Labeling',
    'Orders',
]


DEFAULT_COUNTRY_MAPPINGS = [
    ('Schweiz', '91000741810'),
    ('Italien', '91000741812'),
    ('Rumänien', '91000741814'),
    ('Vereinigtes Königreich', '91000741816'),
    ('Frankreich', '91000741817'),
    ('Croatia', '91000741820'),
    ('Spanien Kanaren', 'ES01'),
    ('Spanien', 'ES01'),
    ('Portugal', '91000741824'),
    ('Elfenbeinküste', '91000741828'),
    ('Deutschland', 'Orsay DE'),
    ('Kongo', 'IAM RCB'),
    ('Senegal', 'IAM SN'),
    ('Deutschland AMAZON', 'DE AMAZON'),
    ('EDEKA', 'EDK1'),
    ('Netherlands', 'NL01'),
    ('Northern Ireland', 'IRL'),
    ('ES', 'ES01'),
    ('IT', '91000741812'),
    ('CH', '91000741810'),
    ('Slowakei', 'SLO'),
    ('Tschechien', 'TSC'),
    ('PL', 'PL'),
    ('HU', 'HU'),
    ('BE', 'BE'),
    ('PT', 'PT'),
    ('AT', 'AT'),
    ('Deutschland C&A', 'DE'),
    ('SI', 'SI'),
]


def seed_data():
    """Seed default activities, admin user and country mappings on first run."""
    if Activity.query.count() == 0:
        for i, name in enumerate(DEFAULT_ACTIVITIES):
            db.session.add(Activity(name=name, sort_order=i))
        db.session.commit()
        print("[SEED] Default activities created.")

    if User.query.filter_by(role='admin').count() == 0:
        admin = User(
            username='admin',
            display_name='Administrator',
            role='admin'
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print("[SEED] Admin user created (login: admin / password: admin123)")

    if CountryMapping.query.count() == 0:
        for country, innenauftrag in DEFAULT_COUNTRY_MAPPINGS:
            db.session.add(CountryMapping(country=country, innenauftrag=innenauftrag))
        db.session.commit()
        print("[SEED] Default country mappings created.")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    app.run(debug=True, host='0.0.0.0', port=5001)
