import os
import time
import sqlite3
import threading
from flask import Flask, request, jsonify, g

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
DB_PATH      = os.environ.get("DB_PATH", "devices.db")
OFFLINE_AFTER = int(os.environ.get("OFFLINE_AFTER", "45"))  # seconds

app = Flask(__name__)


# ------------------------------------------------------------------
# Database helpers
# ------------------------------------------------------------------
def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = sqlite3.connect(DB_PATH, timeout=10)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_db(_exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id         TEXT PRIMARY KEY,
            info       TEXT,
            last_seen  REAL,
            registered REAL
        )
    """)
    con.commit()
    con.close()


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
@app.route("/")
def root():
    return jsonify({
        "service": "z-backend",
        "ok": True,
        "endpoints": ["/register", "/hb", "/devices", "/device/<id>"]
    })


@app.route("/register", methods=["POST"])
def register():
    """Client app calls this once at startup."""
    data = request.get_json(silent=True) or {}
    dev_id = data.get("id")
    if not dev_id:
        return jsonify({"ok": False, "error": "missing id"}), 400

    info = data.get("info", {})
    import json as _json
    info_str = _json.dumps(info) if not isinstance(info, str) else info

    now = time.time()
    db = get_db()
    db.execute("""
        INSERT INTO devices (id, info, last_seen, registered)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            info = excluded.info,
            last_seen = excluded.last_seen
    """, (dev_id, info_str, now, now))
    db.commit()

    return jsonify({"ok": True, "id": dev_id})


@app.route("/hb")
def heartbeat():
    """Client app pings this every ~15s."""
    dev_id = request.args.get("id")
    if not dev_id:
        return jsonify({"ok": False, "error": "missing id"}), 400

    db = get_db()
    cur = db.execute("UPDATE devices SET last_seen=? WHERE id=?",
                     (time.time(), dev_id))
    db.commit()
    if cur.rowcount == 0:
        # unknown device — auto-register so we don't lose it
        now = time.time()
        db.execute("INSERT OR IGNORE INTO devices (id, info, last_seen, registered) "
                   "VALUES (?, ?, ?, ?)", (dev_id, "{}", now, now))
        db.commit()
        return jsonify({"ok": True, "note": "auto-registered"})

    return jsonify({"ok": True})


@app.route("/devices")
def list_devices():
    """Admin app calls this for 'ls devices'."""
    db = get_db()
    rows = db.execute(
        "SELECT id, last_seen, registered FROM devices ORDER BY last_seen DESC"
    ).fetchall()

    now = time.time()
    out = []
    for r in rows:
        online = (now - r["last_seen"]) <= OFFLINE_AFTER
        out.append({
            "id": r["id"],
            "online": online,
            "last_seen": r["last_seen"],
            "age": round(now - r["last_seen"], 1),
        })

    # The admin C++ code reads the "devices" key as a list of strings.
    # So we return a plain list of ids here AND the rich objects under "details".
    return jsonify({
        "devices": [d["id"] for d in out],
        "details": out,
        "count":   len(out),
        "online":  sum(1 for d in out if d["online"]),
    })


@app.route("/device/<dev_id>")
def device_info(dev_id):
    db = get_db()
    row = db.execute(
        "SELECT id, info, last_seen, registered FROM devices WHERE id=?",
        (dev_id,)
    ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "not found"}), 404

    now = time.time()
    return jsonify({
        "ok": True,
        "id": row["id"],
        "info": row["info"],
        "online": (now - row["last_seen"]) <= OFFLINE_AFTER,
        "last_seen": row["last_seen"],
        "registered": row["registered"],
        "age": round(now - row["last_seen"], 1),
    })


# ------------------------------------------------------------------
# Optional: background cleanup of devices inactive > 7 days
# ------------------------------------------------------------------
def cleanup_loop():
    while True:
        try:
            con = sqlite3.connect(DB_PATH, timeout=10)
            cutoff = time.time() - 7 * 24 * 3600
            con.execute("DELETE FROM devices WHERE last_seen < ?", (cutoff,))
            con.commit()
            con.close()
        except Exception:
            pass
        time.sleep(3600)


if __name__ == "__main__":
    init_db()
    threading.Thread(target=cleanup_loop, daemon=True).start()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
else:
    # When run by gunicorn on Render, still ensure the table exists
    init_db()
    threading.Thread(target=cleanup_loop, daemon=True).start()
