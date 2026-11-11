import os
import qrcode

# 1. Define folder layout
PROJECT_DIR = "farmer-attendance"
TEMPLATES_DIR = os.path.join(PROJECT_DIR, "templates")
QR_DIR = os.path.join(PROJECT_DIR, "generated_qr_codes")

os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(QR_DIR, exist_ok=True)

# 2. app.py content
app_code = '''import sqlite3
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
'''

# 3. templates/index.html content
html_code = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Farmer Attendance System</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/html5-qrcode" type="text/javascript"></script>
</head>
<body class="bg-gray-100 min-h-screen text-gray-800">

  <header class="bg-emerald-700 text-white py-4 shadow-md text-center">
    <h1 class="text-2xl font-bold">🌾 Farmer Attendance Station</h1>
    <p class="text-sm opacity-90">Scan your QR badge to Check-In or Check-Out</p>
  </header>

  <main class="max-w-4xl mx-auto p-4 md:p-6 grid grid-cols-1 md:grid-cols-2 gap-6">

    <!-- SCANNER SECTION -->
    <div class="bg-white p-5 rounded-xl shadow-md flex flex-col items-center">
      <h2 class="text-lg font-semibold text-gray-700 mb-3">Camera Scanner</h2>
      
      <!-- Video Container -->
      <div id="reader" class="w-full max-w-sm rounded-lg overflow-hidden border-2 border-dashed border-emerald-500"></div>

      <!-- Live Feedback Alert -->
      <div id="statusBox" class="hidden mt-4 w-full p-4 rounded-lg text-center font-medium transition-all"></div>

      <!-- Manual Code Input Fallback -->
      <div class="mt-4 w-full flex gap-2">
        <input type="text" id="manualCode" placeholder="Enter Code (e.g. FARMER-001)" 
               class="border rounded px-3 py-2 text-sm flex-1 focus:ring-2 focus:ring-emerald-400 outline-none">
        <button onclick="submitCode(document.getElementById('manualCode').value)" 
                class="bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold px-4 py-2 rounded">
          Submit
        </button>
      </div>
    </div>

    <!-- DAILY LOGS TABLE -->
    <div class="bg-white p-5 rounded-xl shadow-md flex flex-col">
      <div class="flex justify-between items-center mb-3">
        <h2 class="text-lg font-semibold text-gray-700">Today's Log</h2>
        <button onclick="fetchTodayLogs()" class="text-xs bg-gray-100 hover:bg-gray-200 px-3 py-1 rounded text-gray-700">🔄 Refresh</button>
      </div>

      <div class="overflow-y-auto max-h-[420px] flex-1">
        <table class="w-full text-left text-sm">
          <thead class="bg-gray-50 border-b text-gray-500">
            <tr>
              <th class="py-2 px-3">Farmer</th>
              <th class="py-2 px-3">In</th>
              <th class="py-2 px-3">Out</th>
              <th class="py-2 px-3">Status</th>
            </tr>
          </thead>
          <tbody id="attendanceTable" class="divide-y"></tbody>
        </table>
      </div>
    </div>

  </main>

  <script>
    let isProcessing = false;

    // Audio feedback using Web Audio API
    function playBeep(success = true) {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = success ? 'sine' : 'square';
        osc.frequency.value = success ? 800 : 300;
        gain.gain.value = 0.15;
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.18);
      } catch(e) {}
    }

    async function submitCode(code) {
      if (!code || isProcessing) return;
      isProcessing = true;

      const statusBox = document.getElementById("statusBox");
      statusBox.className = "mt-4 w-full p-4 rounded-lg text-center font-medium bg-gray-100 text-gray-600 block";
      statusBox.innerHTML = `Verifying <b>${code}</b>...`;

      try {
        const response = await fetch('/api/scan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ qr_code: code })
        });

        const res = await response.json();

        if (response.ok && res.success) {
          playBeep(true);
          if (res.action === 'CHECK_IN') {
            statusBox.className = "mt-4 w-full p-4 rounded-lg text-center font-medium bg-emerald-100 text-emerald-800 block border border-emerald-300";
            statusBox.innerHTML = `✅ <b>Welcome, ${res.name}!</b><br>Checked <b>IN</b> at ${res.time}`;
          } else {
            statusBox.className = "mt-4 w-full p-4 rounded-lg text-center font-medium bg-blue-100 text-blue-800 block border border-blue-300";
            statusBox.innerHTML = `👋 <b>Goodbye, ${res.name}!</b><br>Checked <b>OUT</b> at ${res.time} (Duration: ${res.duration})`;
          }
          fetchTodayLogs();
        } else {
          playBeep(false);
          statusBox.className = "mt-4 w-full p-4 rounded-lg text-center font-medium bg-red-100 text-red-800 block border border-red-300";
          statusBox.innerHTML = `⚠️ ${res.message || 'Scan error'}`;
        }
      } catch (err) {
        statusBox.className = "mt-4 w-full p-4 rounded-lg text-center font-medium bg-red-100 text-red-800 block";
        statusBox.innerText = "Network connection failed.";
      } finally {
        document.getElementById("manualCode").value = "";
        setTimeout(() => { isProcessing = false; }, 3000);
      }
    }

    async function fetchTodayLogs() {
      try {
        const res = await fetch('/api/records');
        const data = await res.json();
        const tbody = document.getElementById('attendanceTable');
        tbody.innerHTML = '';

        if (data.length === 0) {
          tbody.innerHTML = `<tr><td colspan="4" class="text-center py-4 text-gray-400">No records today yet.</td></tr>`;
          return;
        }

        data.forEach(row => {
          const isWorking = !row.check_out;
          const tr = document.createElement('tr');
          tr.className = "hover:bg-gray-50";
          tr.innerHTML = `
            <td class="py-2 px-3">
              <div class="font-semibold text-gray-800">${row.name}</div>
              <div class="text-xs text-gray-400">${row.farmer_code}</div>
            </td>
            <td class="py-2 px-3 text-gray-600">${row.check_in}</td>
            <td class="py-2 px-3 text-gray-600">${row.check_out || '—'}</td>
            <td class="py-2 px-3">
              <span class="px-2 py-0.5 rounded-full text-xs font-semibold ${isWorking ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'}">
                ${isWorking ? 'Working' : 'Completed'}
              </span>
            </td>
          `;
          tbody.appendChild(tr);
        });
      } catch (e) {
        console.error("Failed to load records:", e);
      }
    }

    // Camera scanner
    function onScanSuccess(decodedText) {
      if (!isProcessing) {
        submitCode(decodedText);
      }
    }

    const html5QrcodeScanner = new Html5QrcodeScanner(
      "reader", { fps: 10, qrbox: { width: 220, height: 220 } }, false
    );
    html5QrcodeScanner.render(onScanSuccess);

    fetchTodayLogs();
  </script>
</body>
</html>
'''

# 4. Write server & template files
with open(os.path.join(PROJECT_DIR, "app.py"), "w", encoding="utf-8") as f:
    f.write(app_code)

with open(os.path.join(TEMPLATES_DIR, "index.html"), "w", encoding="utf-8") as f:
    f.write(html_code)

# 5. Generate sample printable QR PNG files
demo_farmers = [
    ("FARMER-001", "Ramesh_Kumar.png"),
    ("FARMER-002", "Suresh_Patel.png"),
    ("FARMER-003", "Anita_Devi.png")
]

for code, filename in demo_farmers:
    qr = qrcode.QRCode(box_size=10, border=3)
    qr.add_data(code)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(os.path.join(QR_DIR, filename))

print("\n" + "=" * 55)
print("✅ SUCCESS! Project created in folder: 'farmer-attendance'")
print("=" * 55)
print("Files generated:")
print("  ├── app.py")
print("  ├── templates/index.html")
print("  └── generated_qr_codes/")
print("        ├── Ramesh_Kumar.png  (Code: FARMER-001)")
print("        ├── Suresh_Patel.png  (Code: FARMER-002)")
print("        └── Anita_Devi.png    (Code: FARMER-003)")
print("\nTo start the application:")
print("  cd farmer-attendance")
print("  python app.py")
print("=" * 55)