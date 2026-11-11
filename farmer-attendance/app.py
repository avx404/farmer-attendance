import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = "attendance.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Farmers database table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS farmers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            phone TEXT
        )
    """)
    
    # Attendance database table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            check_in TEXT NOT NULL,
            check_out TEXT,
            FOREIGN KEY (farmer_id) REFERENCES farmers (id)
        )
    """)
    
    # Populate initial demo farmers if empty
    cursor.execute("SELECT COUNT(*) FROM farmers")
    if cursor.fetchone()[0] == 0:
        demo_farmers = [
            ("FARMER-001", "Ramesh Kumar", "9876543210"),
            ("FARMER-002", "Suresh Patel", "9876543211"),
            ("FARMER-003", "Anita Devi", "9876543212")
        ]
        cursor.executemany("INSERT INTO farmers (farmer_code, name, phone) VALUES (?, ?, ?)", demo_farmers)
        
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/scan', methods=['POST'])
def scan_qr():
    data = request.json or {}
    qr_code = data.get('qr_code', '').strip()

    if not qr_code:
        return jsonify({"success": False, "message": "No QR code provided"}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM farmers WHERE farmer_code = ?", (qr_code,))
    farmer = cursor.fetchone()
    if not farmer:
        conn.close()
        return jsonify({"success": False, "message": f"Unrecognized QR: {qr_code}"}), 404

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M:%S")

    # Check for active session today
    cursor.execute("""
        SELECT * FROM attendance 
        WHERE farmer_id = ? AND date = ? AND check_out IS NULL 
        ORDER BY id DESC LIMIT 1
    """, (farmer['id'], today_str))
    active_session = cursor.fetchone()

    if active_session:
        # Anti-duplicate cooldown (30 seconds)
        check_in_time = datetime.strptime(f"{today_str} {active_session['check_in']}", "%Y-%m-%d %H:%M:%S")
        seconds_passed = (now - check_in_time).total_seconds()
        
        if seconds_passed < 30:
            conn.close()
            return jsonify({
                "success": False,
                "message": f"Already scanned! Wait {int(30 - seconds_passed)}s before checking out."
            }), 429

        # Perform Check-Out
        cursor.execute("UPDATE attendance SET check_out = ? WHERE id = ?", (current_time_str, active_session['id']))
        conn.commit()
        
        hours = round(seconds_passed / 3600, 2)
        conn.close()
        return jsonify({
            "success": True,
            "action": "CHECK_OUT",
            "name": farmer['name'],
            "code": farmer['farmer_code'],
            "time": current_time_str,
            "duration": f"{hours} hrs"
        })
    else:
        # Perform Check-In
        cursor.execute("""
            INSERT INTO attendance (farmer_id, date, check_in) 
            VALUES (?, ?, ?)
        """, (farmer['id'], today_str, current_time_str))
        conn.commit()
        conn.close()
        
        return jsonify({
            "success": True,
            "action": "CHECK_IN",
            "name": farmer['name'],
            "code": farmer['farmer_code'],
            "time": current_time_str
        })

@app.route('/api/records', methods=['GET'])
def get_records():
    conn = get_db()
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT a.id, f.name, f.farmer_code, a.date, a.check_in, a.check_out 
        FROM attendance a
        JOIN farmers f ON a.farmer_id = f.id
        WHERE a.date = ?
        ORDER BY a.id DESC
    """, (today_str,))
    rows = cursor.fetchall()
    conn.close()

    return jsonify([dict(row) for row in rows])

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
