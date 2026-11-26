# LinguaPro – Language Education Center

Web application for enrolling students in language courses.
Front end: HTML + CSS (Jinja templates). Back end: Python (Flask). Database: SQLite.

## Roles

| Role | How to get it | What it can do |
|------|---------------|----------------|
| Student | Register on `/register` (name, username, password, choose courses) | Log in, see own courses, enroll in more, leave a course |
| Administrator | Created automatically on first run | Log in, see all students and their classes, search students, see the class list of each course, and manage everything listed below |

### What the administrator can manage

- **Courses:** add, edit and delete (deleting a course also removes its enrollments).
- **Capacity:** each course has a maximum number of students. Full courses cannot be joined by
  students (on registration or later) or by the admin. The maximum cannot be set lower than the
  number of students already enrolled.
- **Enrollments:** enroll a student in a course or remove them, from the student page or the course page.
- **Students:** reset a student's password and delete a student (their enrollments are removed too).

Default administrator: username `admin`, password `admin123`.
Change it before any real use: set the `ADMIN_PASSWORD` environment variable **before the first run**
(or delete `linguapro.db` and start again).

## Run

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Project structure

```
app.py            Flask routes, database access, login logic
linguapro.db      SQLite database (created on first run)
templates/        HTML pages (base layout + one page per screen)
static/style.css  CSS
```

## Database

- `users` (id, full_name, username, password_hash, role)
- `courses` (id, name, language, level, schedule, teacher, max_students)
- `enrollments` (id, user_id, course_id, enrolled_at) – a student can be enrolled in a course only once

An older `linguapro.db` from the first version is upgraded automatically on start
(existing courses get a maximum of 20 students; change it in the admin panel).
Passwords are stored hashed. Forms use a CSRF token. SQL uses parameters.

## Notes

Set `SECRET_KEY` as an environment variable in any real deployment.
