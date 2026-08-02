import hashlib
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
import tempfile

from flask import Flask, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.utils import secure_filename
BASE_DIR =Path(__file__).resolve().parent
BASE_DIR =Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "static" / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "student-management-secret")
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config["DATABASE_PATH"] = os.environ.get("DATABASE_PATH", str(BASE_DIR / "database" / "student_management.db"))


def ensure_database_path() -> None:
    db_Path = Path(app.config["DATABASE_PATH"])
    db_Path.parent.mkdir(parents=True, exist_ok=True)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(app.config["DATABASE_PATH"])
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    ensure_database_path()
    db = sqlite3.connect(app.config["DATABASE_PATH"])
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin'
        );

        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            register_number TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            course TEXT,
            password TEXT NOT NULL,
            photo TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            attendance_date TEXT NOT NULL,
            status TEXT NOT NULL,
            remarks TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            tuition_fee REAL NOT NULL DEFAULT 0,
            due_amount REAL NOT NULL DEFAULT 0,
            paid_amount REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Pending',
            due_date TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_date TEXT NOT NULL,
            method TEXT NOT NULL,
            receipt_number TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )

    db.execute(
        "INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
        ("admin", hash_password("admin123"), "admin"),
    )
    db.execute(
        "INSERT OR IGNORE INTO students (register_number, full_name, email, phone, course, password, photo, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "1001",
            "Ava Carter",
            "ava@example.com",
            "+1 555 0101",
            "Computer Science",
            hash_password("student123"),
            None,
            datetime.now().strftime("%Y-%m-%d"),
        ),
    )
    db.execute(
        "INSERT OR IGNORE INTO fees (student_id, tuition_fee, due_amount, paid_amount, status, due_date) VALUES (?, ?, ?, ?, ?, ?)",
        (1, 1500.0, 400.0, 1100.0, "Pending", "2026-08-15"),
    )
    db.execute(
        "INSERT OR IGNORE INTO announcements (title, message, created_at) VALUES (?, ?, ?)",
        (
            "Welcome to the new portal",
            "All students can now view attendance, fees, and announcements from a single dashboard.",
            datetime.now().strftime("%Y-%m-%d"),
        ),
    )
    db.commit()
    db.close()


init_db()


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session or "user_role" not in session:
                return redirect(url_for("login"))
            if role and session.get("user_role") != role:
                return redirect(url_for("dashboard") if session.get("user_role") == "admin" else url_for("student_dashboard"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


@app.route("/")
def index():
    if session.get("user_role") == "admin":
        return redirect(url_for("admin_dashboard"))
    if session.get("user_role") == "student":
        return redirect(url_for("student_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        db = get_db()
        admin = db.execute(
            "SELECT id, username, role FROM users WHERE username = ? AND password = ?",
            (username, hash_password(password)),
        ).fetchone()
        if admin:
            session["user_id"] = admin["id"]
            session["user_role"] = admin["role"]
            session["username"] = admin["username"]
            return redirect(url_for("admin_dashboard"))

        student = db.execute(
            "SELECT id, register_number, full_name FROM students WHERE register_number = ? AND password = ?",
            (username, hash_password(password)),
        ).fetchone()
        if student:
            session["user_id"] = student["id"]
            session["user_role"] = "student"
            session["username"] = student["full_name"]
            return redirect(url_for("student_dashboard"))

        return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/dashboard")
@login_required(role="admin")
def admin_dashboard():
    db = get_db()
    total_students = db.execute("SELECT COUNT(*) AS count FROM students").fetchone()["count"]
    total_fees_collected = db.execute("SELECT COALESCE(SUM(paid_amount), 0) AS total FROM fees").fetchone()["total"]
    pending_fees = db.execute("SELECT COALESCE(SUM(due_amount), 0) AS total FROM fees").fetchone()["total"]
    present_today = db.execute(
        "SELECT COUNT(*) AS count FROM attendance WHERE attendance_date = ? AND status = 'Present'",
        (datetime.now().strftime("%Y-%m-%d"),),
    ).fetchone()["count"]
    attendance_percentage = round((present_today / total_students) * 100, 1) if total_students else 0.0

    students = db.execute("SELECT * FROM students ORDER BY full_name").fetchall()
    announcements = db.execute("SELECT * FROM announcements ORDER BY id DESC LIMIT 5").fetchall()

    growth = [6, 8, 10, 15, 18, total_students]
    return render_template(
        "admin_dashboard.html",
        stats={
            "students": total_students,
            "fees_collected": total_fees_collected,
            "pending_fees": pending_fees,
            "attendance": attendance_percentage,
        },
        students=students,
        announcements=announcements,
        growth=growth,
    )


@app.route("/admin/students", methods=["GET", "POST"])
@login_required(role="admin")
def admin_students():
    db = get_db()
    edit_id = request.args.get("edit")
    student_to_edit = None
    if edit_id:
        student_to_edit = db.execute("SELECT * FROM students WHERE id = ?", (edit_id,)).fetchone()

    if request.method == "POST":
        student_id = request.form.get("student_id")
        register_number = request.form.get("register_number", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        course = request.form.get("course", "").strip()
        password = request.form.get("password", "").strip()
        photo_file = request.files.get("photo")
        photo_name = None

        if photo_file and photo_file.filename:
            filename = secure_filename(photo_file.filename)
            photo_name = f"{uuid.uuid4().hex}_{filename}"
            photo_file.save(os.path.join(app.config["UPLOAD_FOLDER"], photo_name))

        if student_id:
            if photo_name:
                db.execute(
                    "UPDATE students SET register_number = ?, full_name = ?, email = ?, phone = ?, course = ?, photo = ? WHERE id = ?",
                    (register_number, full_name, email, phone, course, photo_name, student_id),
                )
            else:
                db.execute(
                    "UPDATE students SET register_number = ?, full_name = ?, email = ?, phone = ?, course = ? WHERE id = ?",
                    (register_number, full_name, email, phone, course, student_id),
                )
            if password:
                db.execute("UPDATE students SET password = ? WHERE id = ?", (hash_password(password), student_id))
        else:
            db.execute(
                "INSERT INTO students (register_number, full_name, email, phone, course, password, photo, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (register_number, full_name, email, phone, course, hash_password(password or "student123"), photo_name, datetime.now().strftime("%Y-%m-%d")),
            )
            student_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            db.execute(
                "INSERT INTO fees (student_id, tuition_fee, due_amount, paid_amount, status, due_date) VALUES (?, ?, ?, ?, ?, ?)",
                (student_id, 1500.0, 1500.0, 0.0, "Pending", (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")),
            )

        db.commit()
        return redirect(url_for("admin_students"))

    search = request.args.get("q", "")
    query = "SELECT * FROM students"
    params = []
    if search:
        query += " WHERE full_name LIKE ? OR register_number LIKE ?"
        params = [f"%{search}%", f"%{search}%"]
    query += " ORDER BY full_name"
    students = db.execute(query, params).fetchall()
    return render_template("students.html", students=students, student_to_edit=student_to_edit, search=search)


@app.route("/admin/students/delete/<int:student_id>")
@login_required(role="admin")
def delete_student(student_id):
    db = get_db()
    db.execute("DELETE FROM students WHERE id = ?", (student_id,))
    db.commit()
    return redirect(url_for("admin_students"))


@app.route("/admin/attendance", methods=["GET", "POST"])
@login_required(role="admin")
def admin_attendance():
    db = get_db()
    selected_date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    if request.method == "POST":
        selected_date = request.form.get("attendance_date", selected_date)
        for student in db.execute("SELECT id FROM students ORDER BY full_name").fetchall():
            status = request.form.get(f"status_{student['id']}", "Absent")
            remarks = request.form.get(f"remarks_{student['id']}", "")
            existing = db.execute(
                "SELECT id FROM attendance WHERE student_id = ? AND attendance_date = ?",
                (student["id"], selected_date),
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE attendance SET status = ?, remarks = ? WHERE id = ?",
                    (status, remarks, existing["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO attendance (student_id, attendance_date, status, remarks) VALUES (?, ?, ?, ?)",
                    (student["id"], selected_date, status, remarks),
                )
        db.commit()
        return redirect(url_for("admin_attendance", date=selected_date))

    students = db.execute("SELECT * FROM students ORDER BY full_name").fetchall()
    attendance_rows = {}
    for row in db.execute(
        "SELECT student_id, status, remarks FROM attendance WHERE attendance_date = ? ORDER BY student_id",
        (selected_date,),
    ).fetchall():
        attendance_rows[row["student_id"]] = row

    monthly_total = db.execute(
        "SELECT COUNT(*) AS count FROM attendance WHERE attendance_date BETWEEN ? AND ?",
        ((datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d")),
    ).fetchone()["count"]
    monthly_present = db.execute(
        "SELECT COUNT(*) AS count FROM attendance WHERE attendance_date BETWEEN ? AND ? AND status = 'Present'",
        ((datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d")),
    ).fetchone()["count"]
    monthly_percentage = round((monthly_present / monthly_total) * 100, 1) if monthly_total else 0.0

    return render_template(
        "attendance.html",
        students=students,
        selected_date=selected_date,
        attendance_rows=attendance_rows,
        monthly_percentage=monthly_percentage,
    )


@app.route("/admin/fees", methods=["GET", "POST"])
@login_required(role="admin")
def admin_fees():
    db = get_db()
    if request.method == "POST":
        student_id = request.form.get("student_id")
        amount = float(request.form.get("amount", 0))
        method = request.form.get("method", "Cash")
        receipt_number = request.form.get("receipt_number", f"RCPT-{uuid.uuid4().hex[:6].upper()}")
        db.execute(
            "INSERT INTO payments (student_id, amount, payment_date, method, receipt_number) VALUES (?, ?, ?, ?, ?)",
            (student_id, amount, datetime.now().strftime("%Y-%m-%d"), method, receipt_number),
        )
        fee = db.execute("SELECT * FROM fees WHERE student_id = ?", (student_id,)).fetchone()
        if fee:
            new_paid = fee["paid_amount"] + amount
            new_due = max(0.0, fee["tuition_fee"] - new_paid)
            status = "Paid" if new_due == 0 else "Pending"
            db.execute(
                "UPDATE fees SET paid_amount = ?, due_amount = ?, status = ? WHERE student_id = ?",
                (new_paid, new_due, status, student_id),
            )
        db.commit()
        return redirect(url_for("admin_fees"))

    fee_rows = db.execute(
        "SELECT s.id, s.full_name, s.register_number, f.tuition_fee, f.due_amount, f.paid_amount, f.status FROM students s LEFT JOIN fees f ON s.id = f.student_id ORDER BY s.full_name"
    ).fetchall()
    students = db.execute("SELECT id, full_name FROM students ORDER BY full_name").fetchall()
    return render_template("fees.html", fee_rows=fee_rows, students=students)


@app.route("/admin/export/students/excel")
@login_required(role="admin")
def export_students_excel():
    db = get_db()
    students = db.execute("SELECT register_number, full_name, email, phone, course FROM students ORDER BY full_name").fetchall()
    rows = ["register_number,full_name,email,phone,course"]
    for student in students:
        rows.append(
            f"{student['register_number']},{student['full_name']},{student['email']},{student['phone']},{student['course']}"
        )
    content = "\n".join(rows)
    response = app.response_class(content, mimetype="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=students.csv"
    return response


@app.route("/admin/export/students/pdf")
@login_required(role="admin")
def export_students_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    db = get_db()
    students = db.execute("SELECT register_number, full_name, email, phone, course FROM students ORDER BY full_name").fetchall()
    temp_path = BASE_DIR / "student_report.pdf"
    pdf = canvas.Canvas(str(temp_path), pagesize=letter)
    pdf.setTitle("Student Report")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, 760, "Student Report")
    pdf.setFont("Helvetica", 11)
    y = 730
    for student in students:
        pdf.drawString(40, y, f"{student['register_number']} - {student['full_name']} | {student['course']}")
        y -= 16
    pdf.save()
    return send_file(temp_path, as_attachment=True, download_name="students.pdf")


@app.route("/student/dashboard")
@login_required(role="student")
def student_dashboard():
    db = get_db()
    student_id = session["user_id"]
    student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    fee = db.execute("SELECT * FROM fees WHERE student_id = ?", (student_id,)).fetchone()
    attendance_rows = db.execute(
        "SELECT attendance_date, status FROM attendance WHERE student_id = ? ORDER BY attendance_date DESC LIMIT 10",
        (student_id,),
    ).fetchall()
    announcements = db.execute("SELECT * FROM announcements ORDER BY id DESC LIMIT 5").fetchall()

    attendance_total = db.execute("SELECT COUNT(*) AS count FROM attendance WHERE student_id = ?", (student_id,)).fetchone()["count"]
    attendance_present = db.execute(
        "SELECT COUNT(*) AS count FROM attendance WHERE student_id = ? AND status = 'Present'",
        (student_id,),
    ).fetchone()["count"]
    attendance_percentage = round((attendance_present / attendance_total) * 100, 1) if attendance_total else 0.0

    return render_template(
        "student_dashboard.html",
        student=student,
        fee=fee,
        attendance_rows=attendance_rows,
        announcements=announcements,
        attendance_percentage=attendance_percentage,
    )


@app.route("/student/profile", methods=["GET", "POST"])
@login_required(role="student")
def student_profile():
    db = get_db()
    student_id = session["user_id"]
    student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        course = request.form.get("course", "").strip()
        photo_file = request.files.get("photo")
        photo_name = student["photo"]
        if photo_file and photo_file.filename:
            filename = secure_filename(photo_file.filename)
            photo_name = f"{uuid.uuid4().hex}_{filename}"
            photo_file.save(os.path.join(app.config["UPLOAD_FOLDER"], photo_name))
        db.execute(
            "UPDATE students SET full_name = ?, email = ?, phone = ?, course = ?, photo = ? WHERE id = ?",
            (full_name, email, phone, course, photo_name, student_id),
        )
        db.commit()
        return redirect(url_for("student_profile"))
    return render_template("student_profile.html", student=student)


@app.route("/student/attendance")
@login_required(role="student")
def student_attendance():
    db = get_db()
    student_id = session["user_id"]
    attendance_rows = db.execute(
        "SELECT attendance_date, status, remarks FROM attendance WHERE student_id = ? ORDER BY attendance_date DESC",
        (student_id,),
    ).fetchall()
    total = db.execute("SELECT COUNT(*) AS count FROM attendance WHERE student_id = ?", (student_id,)).fetchone()["count"]
    present = db.execute(
        "SELECT COUNT(*) AS count FROM attendance WHERE student_id = ? AND status = 'Present'",
        (student_id,),
    ).fetchone()["count"]
    percentage = round((present / total) * 100, 1) if total else 0.0
    return render_template("student_attendance.html", attendance_rows=attendance_rows, percentage=percentage)


@app.route("/student/fees")
@login_required(role="student")
def student_fees():
    db = get_db()
    student_id = session["user_id"]
    fee = db.execute("SELECT * FROM fees WHERE student_id = ?", (student_id,)).fetchone()
    payments = db.execute(
        "SELECT * FROM payments WHERE student_id = ? ORDER BY payment_date DESC",
        (student_id,),
    ).fetchall()
    return render_template("student_fees.html", fee=fee, payments=payments)


@app.route("/student/receipt/<int:fee_id>")
@login_required(role="student")
def student_receipt(fee_id):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    db = get_db()
    fee = db.execute("SELECT * FROM fees WHERE id = ?", (fee_id,)).fetchone()
    student = db.execute("SELECT full_name, register_number FROM students WHERE id = ?", (session["user_id"],)).fetchone()
    temp_path = BASE_DIR / f"receipt_{fee_id}.pdf"
    pdf = canvas.Canvas(str(temp_path), pagesize=letter)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, 760, "Fee Receipt")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(40, 730, f"Student: {student['full_name']}")
    pdf.drawString(40, 710, f"Register Number: {student['register_number']}")
    pdf.drawString(40, 690, f"Tuition Fee: ${fee['tuition_fee']:.2f}")
    pdf.drawString(40, 670, f"Paid Amount: ${fee['paid_amount']:.2f}")
    pdf.drawString(40, 650, f"Due Amount: ${fee['due_amount']:.2f}")
    pdf.drawString(40, 630, f"Status: {fee['status']}")
    pdf.save()
    return send_file(temp_path, as_attachment=True, download_name="receipt.pdf")


@app.route("/student/announcements")
@login_required(role="student")
def student_announcements():
    db = get_db()
    announcements = db.execute("SELECT * FROM announcements ORDER BY id DESC").fetchall()
    return render_template("student_announcements.html", announcements=announcements)


@app.route("/student/change-password", methods=["POST"])
@login_required(role="student")
def student_change_password():
    db = get_db()
    student_id = session["user_id"]
    current_password = request.form.get("current_password", "").strip()
    new_password = request.form.get("new_password", "").strip()
    student = db.execute("SELECT password FROM students WHERE id = ?", (student_id,)).fetchone()
    if student and student["password"] == hash_password(current_password):
        db.execute("UPDATE students SET password = ? WHERE id = ?", (hash_password(new_password), student_id))
        db.commit()
    return redirect(url_for("student_dashboard"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
