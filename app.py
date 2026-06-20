import os
import uuid
from datetime import datetime

from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, send_from_directory, abort, jsonify
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(__file__)
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'invoice-city-dev-key-change-in-prod')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    f'sqlite:///{os.path.join(INSTANCE_DIR, "invoice_city.db")}',
)
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

ALLOWED_EXTENSIONS = {'pdf'}

DEPARTMENTS = [
    'Finance-AP',
    'Transit',
    'Fire',
    'Public Works',
    'Police',
    'Parks and Rec',
]

DEMO_LOGINS = {
    'city': 'ap@demo.city',
    'vendor': 'vendor@contractor.com',
}

STATUS_LABELS = {
    'received': 'Received',
    'in_review': 'In review',
    'approved_for_payment': 'Marked approved for payment',
    'returned': 'Returned to vendor',
    'paid': 'Paid',
}

PO_LINE_CATEGORIES = {
    'services': 'Services',
    'materials': 'Materials',
    'tax': 'Tax (reserved)',
    'other': 'Other',
}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'auth_login'


# ── Models ────────────────────────────────────────────────────────────────

class City(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    departments = db.relationship('Department', backref='city', lazy=True)
    users = db.relationship('User', backref='city', lazy=True)


class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'), nullable=False)
    invoices = db.relationship('Invoice', backref='department', lazy=True)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # city_staff | vendor
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_vendor(self):
        return self.role == 'vendor'

    def is_city_staff(self):
        return self.role == 'city_staff'


class VendorInvite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'), nullable=False)
    vendor_email = db.Column(db.String(120), nullable=False)
    vendor_company = db.Column(db.String(200), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    accepted = db.Column(db.Boolean, default=False)


class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    po_number = db.Column(db.String(100), nullable=False)

    city = db.relationship('City', foreign_keys=[city_id])
    department = db.relationship('Department', foreign_keys=[department_id])
    vendor = db.relationship('User', foreign_keys=[vendor_id])
    lines = db.relationship(
        'POLine', backref='purchase_order', lazy=True,
        order_by='POLine.line_number', cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('city_id', 'po_number', name='uq_city_po_number'),
    )


class POLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    line_number = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(500), nullable=False)
    budget_amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(30), default='other')  # services | materials | tax | other


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'), nullable=False)
    po_number = db.Column(db.String(100))
    invoice_number = db.Column(db.String(100))
    invoice_date = db.Column(db.Date)
    amount = db.Column(db.Float)
    tax_rate = db.Column(db.Float)
    total_amount = db.Column(db.Float)
    description = db.Column(db.Text)
    status = db.Column(db.String(30), default='received')
    return_reason = db.Column(db.Text)
    pdf_filename = db.Column(db.String(300))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    vendor = db.relationship('User', foreign_keys=[vendor_id])
    city = db.relationship('City', foreign_keys=[city_id])
    activities = db.relationship(
        'InvoiceActivity', backref='invoice', lazy=True,
        order_by='InvoiceActivity.created_at', cascade='all, delete-orphan'
    )
    line_items = db.relationship(
        'InvoiceLineItem', backref='invoice', lazy=True,
        order_by='InvoiceLineItem.sort_order', cascade='all, delete-orphan'
    )


class InvoiceLineItem(db.Model):
    """Amount charged against a specific line on the purchase order."""
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    po_line_id = db.Column(db.Integer, db.ForeignKey('po_line.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    po_line = db.relationship('POLine')


class InvoiceActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    body = db.Column(db.Text, nullable=False)
    kind = db.Column(db.String(20), default='note')  # system | note | submission
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author = db.relationship('User', foreign_keys=[author_id])


# ── Helpers ───────────────────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def calc_total(amount, tax_rate):
    return round(amount + (amount * tax_rate / 100), 2)


def po_line_category_label(category):
    return PO_LINE_CATEGORIES.get(category, category.replace('_', ' ').title())


def find_purchase_order(city_id, po_number, vendor_id=None):
    po_number = (po_number or '').strip()
    if not po_number:
        return None
    po = PurchaseOrder.query.filter_by(city_id=city_id, po_number=po_number).first()
    if not po:
        return None
    if vendor_id and po.vendor_id and po.vendor_id != vendor_id:
        return None
    return po


def parse_po_allocations(form, po):
    po_line_ids = form.getlist('po_line_id')
    amounts = form.getlist('po_line_amount')
    valid_lines = {line.id: line for line in po.lines}
    items = []
    for i, line_id in enumerate(po_line_ids):
        if not line_id:
            continue
        po_line = valid_lines.get(int(line_id))
        if not po_line:
            continue
        amount = round(float(amounts[i] or 0), 2)
        if amount <= 0:
            continue
        items.append({
            'po_line_id': po_line.id,
            'amount': amount,
            'sort_order': len(items),
        })
    return items


def allocations_total(items):
    return round(sum(i['amount'] for i in items), 2)


def parse_vendor_invoice_form(form, files, vendor, require_pdf=True):
    """Parse shared vendor submit/resubmit form. Returns (error, payload)."""
    dept_id = form.get('department_id')
    dept = db.session.get(Department, int(dept_id)) if dept_id else None
    if not dept or dept.city_id != vendor.city_id:
        return 'Select a valid department.', None

    file = files.get('pdf')
    pdf_filename = None
    if file and file.filename:
        if not allowed_file(file.filename):
            return 'PDF must be a .pdf file.', None
        pdf_filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
    elif require_pdf:
        return 'PDF required.', None

    po_number = (form.get('po_number') or '').strip()
    purchase_order = find_purchase_order(vendor.city_id, po_number, vendor.id)

    if po_number and not purchase_order:
        return 'PO not found — check the number or contact the city.', None

    allocations = parse_po_allocations(form, purchase_order) if purchase_order else []

    if purchase_order and not allocations:
        return 'Allocate this invoice across at least one PO line (e.g. services, materials, tax).', None

    if purchase_order:
        amount = allocations_total(allocations)
        tax_rate = 0.0
        total = amount
    else:
        amount = float(form.get('amount') or 0)
        tax_rate = float(form.get('tax_rate'))
        total = calc_total(amount, tax_rate)

    if total != round(float(form.get('total_amount')), 2):
        return 'Total does not match your line allocations or amount + tax.', None

    return None, {
        'dept': dept,
        'po_number': po_number or None,
        'purchase_order': purchase_order,
        'allocations': allocations,
        'amount': amount,
        'tax_rate': tax_rate,
        'total': total,
        'invoice_number': form.get('invoice_number'),
        'invoice_date': datetime.strptime(form.get('invoice_date'), '%Y-%m-%d').date(),
        'description': form.get('description'),
        'pdf_filename': pdf_filename,
    }


def apply_invoice_payload(invoice, payload, allocations):
    invoice.department_id = payload['dept'].id
    invoice.po_number = payload['po_number']
    invoice.invoice_number = payload['invoice_number']
    invoice.invoice_date = payload['invoice_date']
    invoice.amount = payload['amount']
    invoice.tax_rate = payload['tax_rate']
    invoice.total_amount = payload['total']
    invoice.description = payload['description']

    for item in list(invoice.line_items):
        db.session.delete(item)
    for item in allocations:
        db.session.add(InvoiceLineItem(invoice_id=invoice.id, **item))


def log_activity(invoice, body, author=None, kind='system'):
    db.session.add(InvoiceActivity(
        invoice_id=invoice.id,
        author_id=author.id if author else None,
        body=body,
        kind=kind,
    ))


def status_label(status, for_vendor=False):
    if for_vendor and status == 'returned':
        return 'Needs action'
    return STATUS_LABELS.get(status, status.replace('_', ' ').title())


def vendor_inbox_departments(vendor_id):
    dept_ids = (
        db.session.query(Invoice.department_id)
        .filter(Invoice.vendor_id == vendor_id, Invoice.status != 'returned')
        .distinct()
    )
    return Department.query.filter(Department.id.in_(dept_ids)).order_by(Department.name).all()


def invoice_visible_to(invoice, user):
    if user.is_vendor():
        return invoice.vendor_id == user.id
    return invoice.city_id == user.city_id


def city_departments(city_id):
    return Department.query.filter_by(city_id=city_id).order_by(Department.name).all()


# ── Auth ──────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def auth_login():
    if current_user.is_authenticated:
        return redirect(url_for('inbox'))
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user)
            return redirect(url_for('inbox'))
        flash('Invalid email or password.', 'error')
    return render_template('auth/login.html')


@app.route('/logout')
@login_required
def auth_logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/register/vendor/<token>', methods=['GET', 'POST'])
def register_vendor(token):
    invite = VendorInvite.query.filter_by(token=token, accepted=False).first()
    if not invite:
        flash('Invalid invitation link.', 'error')
        return redirect(url_for('index'))
    city = db.session.get(City, invite.city_id)
    if request.method == 'POST':
        email = request.form.get('email')
        if email != invite.vendor_email:
            flash('Use the email address you were invited with.', 'error')
            return render_template('vendor/register.html', invite=invite, city=city)
        if User.query.filter_by(email=email).first():
            flash('Account already exists — please log in.', 'error')
            return redirect(url_for('auth_login'))
        user = User(name=request.form.get('name'), email=email, role='vendor', city_id=invite.city_id)
        user.set_password(request.form.get('password'))
        invite.accepted = True
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Welcome! Submit invoices to the department that should receive them.', 'success')
        return redirect(url_for('submit_invoice'))
    return render_template('vendor/register.html', invite=invite, city=city)


@app.route('/')
def index():
    return render_template('index.html', demo_password='demo123')


@app.route('/demo/login/<role>')
def demo_login(role):
    email = DEMO_LOGINS.get(role)
    user = User.query.filter_by(email=email).first() if email else None
    if not user:
        flash('Run python seed_demo.py first.', 'error')
        return redirect(url_for('index'))
    login_user(user)
    return redirect(url_for('inbox'))


# ── Inbox (department-filtered for city) ──────────────────────────────────

@app.route('/inbox')
@login_required
def inbox():
    dept_filter = request.args.get('dept', type=int)
    vendor_view = request.args.get('view', 'active')

    if current_user.is_vendor():
        action_count = Invoice.query.filter_by(
            vendor_id=current_user.id, status='returned',
        ).count()

        if vendor_view == 'action':
            q = Invoice.query.filter_by(vendor_id=current_user.id, status='returned')
            departments = []
            dept_filter = None
        else:
            vendor_view = 'active'
            q = Invoice.query.filter(
                Invoice.vendor_id == current_user.id,
                Invoice.status != 'returned',
            )
            departments = vendor_inbox_departments(current_user.id)
            if dept_filter:
                q = q.filter_by(department_id=dept_filter)

        dept_counts = {}
    else:
        vendor_view = None
        action_count = 0
        q = Invoice.query.filter_by(city_id=current_user.city_id)
        departments = city_departments(current_user.city_id)
        if dept_filter:
            q = q.filter_by(department_id=dept_filter)

        dept_counts = {}
        for d in departments:
            dept_counts[d.id] = Invoice.query.filter_by(
                city_id=current_user.city_id, department_id=d.id
            ).filter(Invoice.status.in_(('received', 'in_review'))).count()

    invoices = q.order_by(Invoice.submitted_at.desc()).all()

    label_fn = (lambda s: status_label(s, for_vendor=True)) if current_user.is_vendor() else status_label

    return render_template(
        'inbox.html',
        invoices=invoices,
        departments=departments,
        dept_filter=dept_filter,
        dept_counts=dept_counts,
        status_label=label_fn,
        vendor_view=vendor_view,
        action_count=action_count,
    )


# ── Vendor submit ─────────────────────────────────────────────────────────

@app.route('/api/purchase-order')
@login_required
def api_purchase_order():
    po_number = (request.args.get('po_number') or '').strip()
    if not po_number:
        return jsonify({'error': 'Enter a PO number.'}), 400

    vendor_id = current_user.id if current_user.is_vendor() else None
    city_id = current_user.city_id
    po = find_purchase_order(city_id, po_number, vendor_id)
    if not po:
        return jsonify({'error': 'PO not found for this city.'}), 404

    return jsonify({
        'po_number': po.po_number,
        'department_id': po.department_id,
        'department_name': po.department.name,
        'lines': [
            {
                'id': line.id,
                'line_number': line.line_number,
                'description': line.description,
                'budget_amount': line.budget_amount,
                'category': line.category,
                'category_label': po_line_category_label(line.category),
            }
            for line in po.lines
        ],
    })


@app.route('/submit', methods=['GET', 'POST'])
@login_required
def submit_invoice():
    if not current_user.is_vendor():
        abort(403)
    city = db.session.get(City, current_user.city_id)
    departments = city_departments(current_user.city_id)

    if request.method == 'POST':
        error, payload = parse_vendor_invoice_form(request.form, request.files, current_user, require_pdf=True)
        if error:
            flash(error, 'error')
            return render_template('vendor/submit.html', city=city, departments=departments)

        file = request.files.get('pdf')
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], payload['pdf_filename']))

        invoice = Invoice(
            vendor_id=current_user.id,
            city_id=current_user.city_id,
            department_id=payload['dept'].id,
            po_number=payload['po_number'],
            invoice_number=payload['invoice_number'],
            invoice_date=payload['invoice_date'],
            amount=payload['amount'],
            tax_rate=payload['tax_rate'],
            total_amount=payload['total'],
            description=payload['description'],
            pdf_filename=payload['pdf_filename'],
            status='received',
        )
        db.session.add(invoice)
        db.session.flush()

        apply_invoice_payload(invoice, payload, payload['allocations'])

        log_activity(invoice, f'{current_user.name} submitted invoice {invoice.invoice_number}', current_user, 'submission')
        log_activity(invoice, f'Routed to {payload["dept"].name}', kind='system')
        if payload['allocations']:
            log_activity(
                invoice,
                f'Charged against {len(payload["allocations"])} PO line(s) · ${payload["amount"]:,.2f}',
                kind='system',
            )
        db.session.commit()

        flash(f'Invoice sent to {payload["dept"].name}.', 'success')
        return redirect(url_for('invoice_detail', invoice_id=invoice.id))

    return render_template('vendor/submit.html', city=city, departments=departments)


@app.route('/invoice/<int:invoice_id>/resubmit', methods=['GET', 'POST'])
@login_required
def resubmit_invoice(invoice_id):
    if not current_user.is_vendor():
        abort(403)
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice or invoice.vendor_id != current_user.id:
        abort(404)
    if invoice.status != 'returned':
        flash('Only returned invoices can be resubmitted.', 'error')
        return redirect(url_for('invoice_detail', invoice_id=invoice_id))

    city = db.session.get(City, current_user.city_id)
    departments = city_departments(current_user.city_id)
    existing_allocations = [
        {'po_line_id': item.po_line_id, 'amount': item.amount}
        for item in invoice.line_items
    ]

    if request.method == 'POST':
        error, payload = parse_vendor_invoice_form(
            request.form, request.files, current_user, require_pdf=False,
        )
        if error:
            flash(error, 'error')
            return render_template(
                'vendor/submit.html',
                city=city,
                departments=departments,
                invoice=invoice,
                resubmit=True,
                existing_allocations=existing_allocations,
            )

        if payload['pdf_filename']:
            file = request.files.get('pdf')
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], payload['pdf_filename']))
            invoice.pdf_filename = payload['pdf_filename']

        apply_invoice_payload(invoice, payload, payload['allocations'])
        invoice.status = 'received'
        invoice.return_reason = None
        invoice.submitted_at = datetime.utcnow()

        log_activity(
            invoice,
            f'{current_user.name} resubmitted invoice {invoice.invoice_number}',
            current_user,
            'submission',
        )
        log_activity(invoice, f'Routed to {payload["dept"].name}', kind='system')
        if payload['allocations']:
            log_activity(
                invoice,
                f'Charged against {len(payload["allocations"])} PO line(s) · ${payload["amount"]:,.2f}',
                kind='system',
            )
        db.session.commit()

        flash(f'Invoice resubmitted to {payload["dept"].name}.', 'success')
        return redirect(url_for('invoice_detail', invoice_id=invoice.id))

    return render_template(
        'vendor/submit.html',
        city=city,
        departments=departments,
        invoice=invoice,
        resubmit=True,
        existing_allocations=existing_allocations,
    )


# ── Invoice file ──────────────────────────────────────────────────────────

@app.route('/invoice/<int:invoice_id>')
@login_required
def invoice_detail(invoice_id):
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice or not invoice_visible_to(invoice, current_user):
        abort(404)
    activities = invoice.activities
    if current_user.is_vendor():
        activities = [a for a in activities if a.kind != 'internal']
    label_fn = (lambda s: status_label(s, for_vendor=True)) if current_user.is_vendor() else status_label
    return render_template(
        'invoice/detail.html',
        invoice=invoice,
        activities=activities,
        status_label=label_fn,
        po_line_category_label=po_line_category_label,
    )


@app.route('/invoice/<int:invoice_id>/action', methods=['POST'])
@login_required
def invoice_action(invoice_id):
    if not current_user.is_city_staff():
        abort(403)
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice or invoice.city_id != current_user.city_id:
        abort(404)

    action = request.form.get('action')
    note = (request.form.get('note') or '').strip()

    if action == 'in_review' and invoice.status == 'received':
        invoice.status = 'in_review'
        log_activity(invoice, f'{current_user.name} marked in review', current_user)
    elif action == 'approve' and invoice.status in ('received', 'in_review'):
        invoice.status = 'approved_for_payment'
        log_activity(invoice, f'{current_user.name} marked approved for payment', current_user)
        if note:
            log_activity(invoice, note, current_user, 'note')
    elif action == 'paid' and invoice.status == 'approved_for_payment':
        invoice.status = 'paid'
        log_activity(invoice, f'{current_user.name} marked paid', current_user)
    elif action == 'return' and invoice.status in ('received', 'in_review'):
        if not note:
            flash('Reason required when returning to vendor.', 'error')
            return redirect(url_for('invoice_detail', invoice_id=invoice_id))
        invoice.status = 'returned'
        invoice.return_reason = note
        log_activity(invoice, f'{current_user.name} returned to vendor — {note}', current_user)
    elif action == 'reopen' and invoice.status == 'returned':
        invoice.status = 'received'
        invoice.return_reason = None
        log_activity(invoice, f'{current_user.name} reopened file', current_user)
    elif action == 'note' and note:
        log_activity(invoice, note, current_user, 'note')
    else:
        flash('That action is not available.', 'error')
        return redirect(url_for('invoice_detail', invoice_id=invoice_id))

    db.session.commit()
    flash('Updated.', 'success')
    return redirect(url_for('invoice_detail', invoice_id=invoice_id))


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/invite-vendor', methods=['GET', 'POST'])
@login_required
def invite_vendor():
    if not current_user.is_city_staff():
        abort(403)
    city = db.session.get(City, current_user.city_id)
    if request.method == 'POST':
        token = uuid.uuid4().hex
        invite = VendorInvite(
            city_id=city.id,
            vendor_email=request.form.get('vendor_email'),
            vendor_company=request.form.get('vendor_company'),
            token=token,
        )
        db.session.add(invite)
        db.session.commit()
        link = url_for('register_vendor', token=token, _external=True)
        flash(f'Invite link (share with vendor): {link}', 'success')
        return redirect(url_for('inbox'))
    return render_template('vendor/invite.html', city=city)


def init_app():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    with app.app_context():
        db.create_all()
        if not User.query.first():
            from seed_demo import seed
            seed()


init_app()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, host='0.0.0.0', port=port)
