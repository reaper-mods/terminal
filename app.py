from flask import Flask, request, jsonify
import time

app = Flask(__name__)
devices = {}

@app.route("/register", methods=["POST"])
def register():
    d = request.get_json(force=True)
    devices[d["id"]] = {"info": d.get("info"), "last_seen": time.time()}
    return {"ok": True}

@app.route("/hb")
def hb():
    i = request.args.get("id")
    if i in devices:
        devices[i]["last_seen"] = time.time()
    return {"ok": True}

@app.route("/devices")
def list_devices():
    return jsonify({"devices": list(devices.keys())})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
