"""LinguaPro - Language Education Center
Flask + SQLite web app with two roles: student and administrator.
"""
import os
import secrets
import sqlite3
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "linguapro.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")

DEFAULT_MAX_STUDENTS = 20


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT NOT NULL,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('student', 'admin')),
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS courses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    language     TEXT NOT NULL,
    level        TEXT NOT NULL,
    schedule     TEXT NOT NULL,
    teacher      TEXT NOT NULL,
    max_students INTEGER NOT NULL DEFAULT 20
);

CREATE TABLE IF NOT EXISTS enrollments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    enrolled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, course_id)
);
"""

# name, language, level, schedule, teacher, max_students
SEED_COURSES = [
    ("English A2", "English", "A2", "Mon & Wed 17:00-18:30", "Anna Kowalska", 15),
    ("English B1", "English", "B1", "Tue & Thu 17:00-18:30", "Anna Kowalska", 15),
    ("English B2", "English", "B2", "Mon & Wed 19:00-20:30", "John Smith", 12),
    ("German A1", "German", "A1", "Tue & Thu 18:00-19:30", "Katarzyna Nowak", 12),
    ("German B1", "German", "B1", "Fri 16:00-19:00", "Katarzyna Nowak", 10),
    ("Spanish A1", "Spanish", "A1", "Wed 18:00-21:00", "Maria Lopez", 10),
    ("French A2", "French", "A2", "Thu 17:30-20:30", "Pierre Dubois", 10),
]


def init_db():
    """Create tables, upgrade older databases, seed admin account and courses."""
    db = sqlite3.connect(DATABASE)
    db.executescript(SCHEMA)

    # Upgrade a database created by the first version (no max_students column).
    columns = [r[1] for r in db.execute("PRAGMA table_info(courses)")]
    if "max_students" not in columns:
        db.execute("ALTER TABLE courses ADD COLUMN max_students "
                   f"INTEGER NOT NULL DEFAULT {DEFAULT_MAX_STUDENTS}")

    if db.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO courses (name, language, level, schedule, teacher, max_students) "
            "VALUES (?, ?, ?, ?, ?, ?)", SEED_COURSES)
    if db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] == 0:
        admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
        db.execute(
            "INSERT INTO users (full_name, username, password_hash, role) "
            "VALUES (?, ?, ?, 'admin')",
            ("Administrator", "admin", generate_password_hash(admin_password)))
    db.commit()
    db.close()


# ---------------------------------------------------------------- helpers
ENROLL_MESSAGES = {
    "ok": ("Enrolled.", "success"),
    "exists": ("Already enrolled in that course.", "error"),
    "full": ("That course is full.", "error"),
    "missing": ("Course not found.", "error"),
}


def courses_with_counts(db):
    """All courses with an `enrolled` column (current number of students)."""
    return db.execute(
        "SELECT c.*, COUNT(e.id) AS enrolled FROM courses c "
        "LEFT JOIN enrollments e ON e.course_id = c.id "
        "GROUP BY c.id ORDER BY c.language, c.level").fetchall()


def enroll_user(db, user_id, course_id):
    """Enroll a user unless the course is full. Returns 'ok', 'exists',
    'full' or 'missing'. The capacity check and the insert are one statement,
    so two people cannot take the last seat at the same time."""
    cur = db.execute(
        "INSERT OR IGNORE INTO enrollments (user_id, course_id) "
        "SELECT ?, c.id FROM courses c WHERE c.id = ? "
        "AND (SELECT COUNT(*) FROM enrollments WHERE course_id = c.id) < c.max_students",
        (user_id, course_id))
    db.commit()
    if cur.rowcount == 1:
        return "ok"
    if not db.execute("SELECT 1 FROM courses WHERE id = ?", (course_id,)).fetchone():
        return "missing"
    if db.execute("SELECT 1 FROM enrollments WHERE user_id = ? AND course_id = ?",
                  (user_id, course_id)).fetchone():
        return "exists"
    return "full"


def get_student_or_404(db, student_id):
    student = db.execute("SELECT * FROM users WHERE id = ? AND role = 'student'",
                         (student_id,)).fetchone()
    if not student:
        abort(404)
    return student


def get_course_or_404(db, course_id):
    course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course:
        abort(404)
    return course


def clean_course_form(form):
    """Validate the add/edit course form. Returns (data, error)."""
    data = {k: form.get(k, "").strip()
            for k in ("name", "language", "level", "schedule", "teacher")}
    try:    
        data["max_students"] = int(form.get("max_students", "").strip())
    except ValueError:
        data["max_students"] = None
    error = None
    if not all(data[k] for k in ("name", "language", "level", "schedule", "teacher")):
        error = "Please fill in all fields."
    elif data["max_students"] is None or not 1 <= data["max_students"] <= 500:
        error = "Maximum students must be a whole number between 1 and 500."
    return data, error


# ---------------------------------------------------------------- security
@app.before_request
def csrf_protect():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST":
        token = request.form.get("csrf", "")
        if not secrets.compare_digest(token, session["csrf"]):
            abort(400, "Invalid form token")


@app.context_processor
def inject_globals():
    return {"csrf_token": session.get("csrf", ""),
            "current_role": session.get("role"),
            "current_name": session.get("name")}


def login_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") != role:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


# ---------------------------------------------------------------- public pages
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    db = get_db()
    courses = courses_with_counts(db)
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        chosen = request.form.getlist("courses")

        error = None
        if not full_name or not username or not password:
            error = "Please fill in all fields."
        elif len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        elif db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            error = "That username is already taken."

        if error:
            flash(error, "error")
            return render_template("register.html", courses=courses,
                                   form=request.form, chosen=chosen)

        cur = db.execute(
            "INSERT INTO users (full_name, username, password_hash, role) "
            "VALUES (?, ?, ?, 'student')",
            (full_name, username, generate_password_hash(password)))
        user_id = cur.lastrowid
        valid_ids = {str(c["id"]) for c in courses}
        full = []
        for cid in chosen:
            if cid in valid_ids and enroll_user(db, user_id, int(cid)) == "full":
                full.append(cid)
        db.commit()
        message = "Account created. You can log in now."
        if full:
            names = ", ".join(c["name"] for c in courses if str(c["id"]) in full)
            message += f" These courses were full and were skipped: {names}."
        flash(message, "success")
        return redirect(url_for("login"))
    return render_template("register.html", courses=courses, form={}, chosen=[])


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?",
                                (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["csrf"] = secrets.token_hex(16)
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["name"] = user["full_name"]
            return redirect(url_for("admin_dashboard" if user["role"] == "admin"
                                    else "student_dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------- student area
@app.route("/student")
@login_required("student")
def student_dashboard():
    db = get_db()
    uid = session["user_id"]
    # A student deleted by the admin while logged in must not keep a session.
    if not db.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
        session.clear()
        flash("Your account no longer exists.", "error")
        return redirect(url_for("login"))
    my_courses = db.execute(
        "SELECT c.*, e.enrolled_at FROM enrollments e "
        "JOIN courses c ON c.id = e.course_id "
        "WHERE e.user_id = ? ORDER BY c.language, c.level", (uid,)).fetchall()
    my_ids = {c["id"] for c in my_courses}
    available = [c for c in courses_with_counts(db) if c["id"] not in my_ids]
    return render_template("student.html", my_courses=my_courses, available=available)


@app.route("/student/enroll", methods=["POST"])
@login_required("student")
def student_enroll():
    course_id = request.form.get("course_id", type=int)
    result = enroll_user(get_db(), session["user_id"], course_id) if course_id else "missing"
    message, category = ENROLL_MESSAGES[result]
    flash("You are now enrolled." if result == "ok" else message, category)
    return redirect(url_for("student_dashboard"))


@app.route("/student/drop", methods=["POST"])
@login_required("student")
def student_drop():
    db = get_db()
    course_id = request.form.get("course_id", type=int)
    db.execute("DELETE FROM enrollments WHERE user_id = ? AND course_id = ?",
               (session["user_id"], course_id))
    db.commit()
    flash("Course removed from your list.", "success")
    return redirect(url_for("student_dashboard"))


# ---------------------------------------------------------------- admin: overview
@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    db = get_db()
    q = request.args.get("q", "").strip()
    sql = ("SELECT u.id, u.full_name, u.username, u.created_at, "
           "GROUP_CONCAT(c.name, ', ') AS courses, COUNT(c.id) AS course_count "
           "FROM users u "
           "LEFT JOIN enrollments e ON e.user_id = u.id "
           "LEFT JOIN courses c ON c.id = e.course_id "
           "WHERE u.role = 'student' ")
    params = []
    if q:
        sql += "AND (u.full_name LIKE ? OR u.username LIKE ?) "
        params += [f"%{q}%", f"%{q}%"]
    sql += "GROUP BY u.id ORDER BY u.full_name"
    students = db.execute(sql, params).fetchall()
    return render_template("admin.html", students=students,
                           course_stats=courses_with_counts(db), q=q)


# ---------------------------------------------------------------- admin: courses
@app.route("/admin/course/new", methods=["GET", "POST"])
@login_required("admin")
def admin_course_new():
    if request.method == "POST":
        data, error = clean_course_form(request.form)
        if error:
            flash(error, "error")
            return render_template("course_form.html", course=request.form, course_id=None)
        db = get_db()
        db.execute(
            "INSERT INTO courses (name, language, level, schedule, teacher, max_students) "
            "VALUES (:name, :language, :level, :schedule, :teacher, :max_students)", data)
        db.commit()
        flash(f"Course '{data['name']}' added.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("course_form.html",
                           course={"max_students": DEFAULT_MAX_STUDENTS}, course_id=None)


@app.route("/admin/course/<int:course_id>")
@login_required("admin")
def admin_course(course_id):
    db = get_db()
    course = get_course_or_404(db, course_id)
    students = db.execute(
        "SELECT u.id, u.full_name, u.username, e.enrolled_at FROM enrollments e "
        "JOIN users u ON u.id = e.user_id WHERE e.course_id = ? "
        "ORDER BY u.full_name", (course_id,)).fetchall()
    candidates = db.execute(
        "SELECT id, full_name, username FROM users WHERE role = 'student' AND id NOT IN "
        "(SELECT user_id FROM enrollments WHERE course_id = ?) ORDER BY full_name",
        (course_id,)).fetchall()
    return render_template("admin_course.html", course=course, students=students,
                           candidates=candidates,
                           is_full=len(students) >= course["max_students"])


@app.route("/admin/course/<int:course_id>/edit", methods=["GET", "POST"])
@login_required("admin")
def admin_course_edit(course_id):
    db = get_db()
    course = get_course_or_404(db, course_id)
    if request.method == "POST":
        data, error = clean_course_form(request.form)
        enrolled = db.execute("SELECT COUNT(*) FROM enrollments WHERE course_id = ?",
                              (course_id,)).fetchone()[0]
        if not error and data["max_students"] < enrolled:
            error = (f"{enrolled} students are already enrolled, so the maximum "
                     f"cannot be lower than {enrolled}.")
        if error:
            flash(error, "error")
            return render_template("course_form.html", course=request.form,
                                   course_id=course_id)
        data["id"] = course_id
        db.execute(
            "UPDATE courses SET name = :name, language = :language, level = :level, "
            "schedule = :schedule, teacher = :teacher, max_students = :max_students "
            "WHERE id = :id", data)
        db.commit()
        flash("Course updated.", "success")
        return redirect(url_for("admin_course", course_id=course_id))
    return render_template("course_form.html", course=dict(course), course_id=course_id)


@app.route("/admin/course/<int:course_id>/delete", methods=["POST"])
@login_required("admin")
def admin_course_delete(course_id):
    db = get_db()
    course = get_course_or_404(db, course_id)
    count = db.execute("SELECT COUNT(*) FROM enrollments WHERE course_id = ?",
                       (course_id,)).fetchone()[0]
    db.execute("DELETE FROM courses WHERE id = ?", (course_id,))  # enrollments cascade
    db.commit()
    flash(f"Course '{course['name']}' deleted ({count} enrollments removed).", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------- admin: students
@app.route("/admin/student/<int:student_id>")
@login_required("admin")
def admin_student(student_id):
    db = get_db()
    student = get_student_or_404(db, student_id)
    courses = db.execute(
        "SELECT c.*, e.enrolled_at FROM enrollments e "
        "JOIN courses c ON c.id = e.course_id "
        "WHERE e.user_id = ? ORDER BY c.language, c.level", (student_id,)).fetchall()
    my_ids = {c["id"] for c in courses}
    available = [c for c in courses_with_counts(db) if c["id"] not in my_ids]
    return render_template("admin_student.html", student=student, courses=courses,
                           available=available)


@app.route("/admin/student/<int:student_id>/password", methods=["POST"])
@login_required("admin")
def admin_student_password(student_id):
    db = get_db()
    get_student_or_404(db, student_id)
    password = request.form.get("password", "")
    if len(password) < 6:
        flash("The new password must be at least 6 characters.", "error")
    else:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                   (generate_password_hash(password), student_id))
        db.commit()
        flash("Password changed. Tell the student the new password.", "success")
    return redirect(url_for("admin_student", student_id=student_id))


@app.route("/admin/student/<int:student_id>/delete", methods=["POST"])
@login_required("admin")
def admin_student_delete(student_id):
    db = get_db()
    student = get_student_or_404(db, student_id)
    db.execute("DELETE FROM users WHERE id = ? AND role = 'student'", (student_id,))
    db.commit()  # enrollments cascade
    flash(f"Student '{student['full_name']}' deleted.", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------- admin: enrollments
def _back(back, student_id, course_id):
    if back == "course":
        return redirect(url_for("admin_course", course_id=course_id))
    return redirect(url_for("admin_student", student_id=student_id))


@app.route("/admin/enrollment/add", methods=["POST"])
@login_required("admin")
def admin_enrollment_add():
    db = get_db()
    student_id = request.form.get("student_id", type=int)
    course_id = request.form.get("course_id", type=int)
    back = request.form.get("back")
    if not student_id or not course_id:
        flash("Please choose from the list first.", "error")
        return _back(back, student_id or 0, course_id or 0) if (
            student_id or course_id) else redirect(url_for("admin_dashboard"))
    student = get_student_or_404(db, student_id)
    course = get_course_or_404(db, course_id)
    result = enroll_user(db, student_id, course_id)
    if result == "ok":
        flash(f"{student['full_name']} enrolled in {course['name']}.", "success")
    else:
        message, category = ENROLL_MESSAGES[result]
        flash(message, category)
    return _back(back, student_id, course_id)


@app.route("/admin/enrollment/remove", methods=["POST"])
@login_required("admin")
def admin_enrollment_remove():
    db = get_db()
    student_id = request.form.get("student_id", type=int)
    course_id = request.form.get("course_id", type=int)
    student = get_student_or_404(db, student_id)
    course = get_course_or_404(db, course_id)
    db.execute("DELETE FROM enrollments WHERE user_id = ? AND course_id = ?",
               (student_id, course_id))
    db.commit()
    flash(f"{student['full_name']} removed from {course['name']}.", "success")
    return _back(request.form.get("back"), student_id, course_id)


if __name__ == "__main__":
    init_db()
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
