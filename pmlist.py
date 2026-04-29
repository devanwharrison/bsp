from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key-change-this")

# =========================================================
# DATABASE
# =========================================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB = os.path.join(DATA_DIR, "cmms.db")

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def safe_int(v, default=0):
    try:
        return int(v)
    except:
        return default

# =========================================================
# INIT DB
# =========================================================
def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT DEFAULT 'tech'
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        tag TEXT,
        current INTEGER,
        last INTEGER,
        interval INTEGER,
        date TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS pending_updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        equipment_id INTEGER,
        user_id INTEGER,
        name TEXT,
        tag TEXT,
        current INTEGER,
        last INTEGER,
        interval INTEGER,
        date TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS system_meta (
        id INTEGER PRIMARY KEY,
        owner_name TEXT
    )
    """)

    c.execute("""
    INSERT OR IGNORE INTO system_meta (id, owner_name)
    VALUES (1, 'System Owner')
    """)

    conn.commit()
    conn.close()

init_db()

# =========================================================
# STATUS
# =========================================================
def calc_status(current, last, interval):
    used = current - last

    if used < interval * 0.75:
        return "Good"
    elif used < interval:
        return "Due Soon"
    elif used < interval * 1.25:
        return "Due"
    return "Overdue"

# =========================================================
# LOGIN
# =========================================================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE username=?", (request.form["username"],))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user["password"], request.form["password"]):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            return redirect("/dashboard")

        return "Invalid login"

    return render_template("login.html")

# =========================================================
# ✅ REGISTER (FIX ADDED)
# =========================================================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        conn = get_db()
        c = conn.cursor()

        hashed_pw = generate_password_hash(request.form["password"])

        try:
            c.execute("""
            INSERT INTO users (username, password, role)
            VALUES (?, ?, 'tech')
            """, (
                request.form["username"],
                hashed_pw
            ))

            conn.commit()
            conn.close()
            return redirect("/")

        except sqlite3.IntegrityError:
            return "User already exists"

    return render_template("register.html")

# =========================================================
# DASHBOARD
# =========================================================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")

    return render_template("dashboard.html", role=session["role"])

# =========================================================
# API EQUIPMENT
# =========================================================
@app.route("/api/equipment")
def api_equipment():
    conn = get_db()
    c = conn.cursor()

    search = request.args.get("search", "")

    c.execute("""
    SELECT * FROM equipment
    WHERE name LIKE ?
    """, (f"%{search}%",))

    rows = c.fetchall()
    conn.close()

    return jsonify([
        {
            "id": r["id"],
            "name": r["name"],
            "tag": r["tag"],
            "current": r["current"],
            "last": r["last"],
            "interval": r["interval"],
            "date": r["date"],
            "status": calc_status(r["current"], r["last"], r["interval"])
        }
        for r in rows
    ])

# =========================================================
# ADD EQUIPMENT
# =========================================================
@app.route("/add", methods=["POST"])
def add():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    INSERT INTO equipment (user_id, name, tag, current, last, interval, date)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        request.form["name"],
        request.form["tag"],
        safe_int(request.form["current"]),
        safe_int(request.form["last"]),
        safe_int(request.form["interval"]),
        request.form["date"]
    ))

    conn.commit()
    conn.close()

    return redirect("/dashboard")

# =========================================================
# SUBMIT UPDATE
# =========================================================
@app.route("/submit_update/<int:id>", methods=["POST"])
def submit_update(id):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    INSERT INTO pending_updates
    (equipment_id, user_id, name, tag, current, last, interval, date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        id,
        session["user_id"],
        request.form["name"],
        request.form["tag"],
        safe_int(request.form["current"]),
        safe_int(request.form["last"]),
        safe_int(request.form["interval"]),
        request.form["date"]
    ))

    conn.commit()
    conn.close()

    return "PENDING"

# =========================================================
# APPROVALS
# =========================================================
@app.route("/approvals")
def approvals():
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM pending_updates")
    updates = c.fetchall()

    conn.close()

    return render_template("approvals.html", updates=updates)

# =========================================================
# APPROVE
# =========================================================
@app.route("/approve/<int:id>")
def approve(id):
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM pending_updates WHERE id=?", (id,))
    u = c.fetchone()

    if u:
        c.execute("""
        UPDATE equipment
        SET name=?, tag=?, current=?, last=?, interval=?, date=?
        WHERE id=?
        """, (
            u["name"],
            u["tag"],
            u["current"],
            u["last"],
            u["interval"],
            u["date"],
            u["equipment_id"]
        ))

        c.execute("DELETE FROM pending_updates WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return redirect("/approvals")

# =========================================================
# REJECT
# =========================================================
@app.route("/reject/<int:id>")
def reject(id):
    conn = get_db()
    c = conn.cursor()

    c.execute("DELETE FROM pending_updates WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return redirect("/approvals")

# =========================================================
# LOGOUT
# =========================================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":
    app.run(debug=True)