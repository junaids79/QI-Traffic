from datetime import datetime, timedelta
import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, flash
from werkzeug.security import check_password_hash

from database import init_db, connect
from routing import (
    NODES, DATA, ACTIVE_BLOCKED_EDGES, edges, shortest, alternative_routes,
    qpso, metrics, fitness, fitness_breakdown, risk_for_path, benchmark,
)
from vrp import solve_vrp

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")
app.config["JSON_SORT_KEYS"] = False
init_db()
BASE_DIR = Path(__file__).resolve().parent
NETWORK_PATH = BASE_DIR / "data" / "network.json"
TRAFFIC_FACTOR = {"LOW": 1.0, "MEDIUM": 1.25, "HIGH": 1.6, "VERY_HIGH": 2.2}


def current_user():
    return session.get("user")


def logged_in():
    return bool(current_user())


def page(template, **context):
    return render_template(template, user=current_user(), **context) if logged_in() else redirect("/")


def error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


@app.route("/", methods=["GET", "POST"])
def login():
    if logged_in():
        return redirect("/dashboard")
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Enter both username and password.", "error")
        else:
            connection = connect()
            record = connection.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            connection.close()
            if record and check_password_hash(record["password_hash"], password):
                session["user"] = {"id": record["id"], "username": record["username"], "role": record["role"]}
                return redirect("/dashboard")
            flash("Invalid credentials. Try the demo account shown below.", "error")
    return render_template("login.html", user=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/dashboard")
def dashboard():
    return page("dashboard.html", nodes=NODES)


@app.route("/benchmark")
def benchmark_page():
    return page("benchmark.html")




@app.route("/vrp")
def vrp_page():
    return page("vrp.html", nodes=NODES)


@app.route("/analytics")
def analytics_page():
    return page("analytics.html")


@app.route("/emergency")
def emergency_page():
    return page("emergency.html", nodes=NODES)


@app.route("/admin")
def admin_page():
    return page("admin.html")


@app.route("/network")
def network_page():
    return page("network.html")


@app.route("/qpso")
def qpso_page():
    return page("qpso.html")


@app.route("/settings")
def settings_page():
    return page("settings.html")


@app.route("/api/network")
def network_api():
    return jsonify({"ok": True, "coverage": "Hyderabad urban road network — selected study area", "network_source": "Curated Hyderabad landmark anchors with a local synthetic junction graph; OpenStreetMap is used for optional route geometry.", "nodes": list(NODES.values()), "edges": edges()})


def pack_route(path, milliseconds=0.0, deadline=0.0, algorithm="Route", weights=None):
    distance, travel_time, traffic_cost = metrics(path)
    risk = risk_for_path(path, deadline)
    deadline_penalty = max(0.0, travel_time - deadline) if deadline > 0 else 0.0
    eta = datetime.now() + timedelta(minutes=travel_time) if path else None
    avg_speed = distance / travel_time * 60.0 if path and travel_time > 0 else 0.0
    return {
        "algorithm": algorithm, "path": ([path[0]["source"]] + [e["destination"] for e in path]) if path else [],
        "distance": round(distance, 2), "travel_time": round(travel_time, 2), "traffic_cost": round(traffic_cost, 2),
        "fitness": round(fitness(path, deadline, weights), 2), "execution_ms": round(milliseconds, 3), "valid": bool(path),
        "deadline_minutes": deadline or None, "deadline_met": bool(path) and (deadline <= 0 or travel_time <= deadline),
        "deadline_penalty": round(deadline_penalty, 2), "eta": eta.strftime("%H:%M") if eta else None,
        "average_speed": round(avg_speed, 2), "risk_score": risk["score"], "risk_level": risk["level"],
        "risk_explanation": risk["explanation"], "score_breakdown": risk["components"],
        "objective_contributions": fitness_breakdown(path, deadline, weights),
        "validation": "Valid path" if path else "No feasible path",
    }


@app.route("/api/route", methods=["POST"])
def route_api():
    if not logged_in():
        return error("Login required", 401)
    payload = request.get_json(silent=True) or {}
    source, destination = payload.get("source"), payload.get("destination")
    vehicle = str(payload.get("vehicle", "Car"))[:40]
    emergency = bool(payload.get("emergency"))
    if source not in NODES or destination not in NODES or source == destination:
        return error("Choose two different locations from the network.")
    if emergency and current_user()["role"] not in ("EMERGENCY_USER", "ADMIN"):
        return error("Emergency routing requires an emergency or admin account.", 403)
    try:
        deadline = max(0.0, min(1440.0, float(payload.get("deadline") or 0)))
    except (TypeError, ValueError):
        deadline = 0.0
    raw_weights = payload.get("weights") if isinstance(payload.get("weights"), dict) else {}
    weights = {k: max(0.0, min(10.0, float(raw_weights.get(k, 0)))) for k in ("time", "distance", "congestion", "deadline") if str(raw_weights.get(k, "")).strip()}
    try:
        t0 = time.perf_counter(); dijkstra = shortest(source, destination, vehicle, emergency); dms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter(); astar = shortest(source, destination, vehicle, emergency, True); ams = (time.perf_counter() - t0) * 1000
        qpso_path, best_curve, mean_curve, qms = qpso(source, destination, vehicle, emergency, deadline=deadline, weights=weights or None)
        alternatives = alternative_routes(source, destination, vehicle, emergency, limit=4)
    except Exception:
        return error("The optimization engine could not find a route for this selection.", 422)
    candidates = {"DIJKSTRA": pack_route(dijkstra, dms, deadline, "Dijkstra", weights), "ASTAR": pack_route(astar, ams, deadline, "A*", weights), "QPSO": pack_route(qpso_path, qms, deadline, "QPSO", weights)}
    # decision_score is just each candidate's fitness (with the invalid-path guard) — it is
    # never a second, separately-weighted formula, so it always agrees with the sliders the
    # user actually set and with the number shown as "fitness" on each card.
    def decision(item):
        return item["fitness"] if item["valid"] else 1e9
    for item in candidates.values(): item["decision_score"] = round(decision(item), 2)
    recommended_key = min(candidates, key=lambda key: candidates[key]["decision_score"])
    recommended = candidates[recommended_key]
    runner_up_key = min((k for k in candidates if k != recommended_key), key=lambda key: candidates[key]["decision_score"])
    runner_up = candidates[runner_up_key]
    why_won = {
        "winner": recommended_key, "runner_up": runner_up_key,
        "winner_fitness": recommended["fitness"], "runner_up_fitness": runner_up["fitness"],
        "margin": round(runner_up["fitness"] - recommended["fitness"], 2) if runner_up["valid"] else None,
        "winner_contributions": recommended["objective_contributions"],
        "runner_up_contributions": runner_up["objective_contributions"],
    }
    return jsonify({"ok": True, "dijkstra": candidates["DIJKSTRA"], "astar": candidates["ASTAR"], "qpso": candidates["QPSO"], "alternatives": [pack_route(p, 0, deadline, f"Alternative {i+1}", weights) for i, p in enumerate(alternatives)], "recommended_algorithm": recommended_key, "why_won": why_won, "convergence": best_curve, "convergence_mean": mean_curve, "active_incidents": [f"{a}->{b}" for a, b in sorted(ACTIVE_BLOCKED_EDGES)], "objective_weights": weights or {"time": .45, "distance": .25, "congestion": .25, "deadline": .05}, "message": "Emergency optimization complete." if emergency else "Route comparison complete using simulated traffic weights."})


@app.route("/api/traffic/live")
def live_traffic_api():
    """Return a map-ready live snapshot, or an explicitly labeled fallback.

    A provider adapter is intentionally opt-in: it expects TRAFFIC_API_URL to
    return {"edges": [{"source", "destination", "traffic_level", "current_speed"}]}.
    Missing credentials, timeouts, and malformed data never break the map.
    """
    provider_url = os.getenv("TRAFFIC_API_URL", "").strip()
    provider_key = os.getenv("TRAFFIC_API_KEY", "").strip()
    if provider_url and provider_key:
        try:
            request_obj = urllib.request.Request(provider_url, headers={"Authorization": f"Bearer {provider_key}", "Accept": "application/json"})
            with urllib.request.urlopen(request_obj, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
            incoming = payload.get("edges") if isinstance(payload, dict) else None
            if not isinstance(incoming, list):
                raise ValueError("Provider response must contain an edges array")
            valid = {(e["source"], e["destination"]): e for e in incoming if isinstance(e, dict) and e.get("source") in NODES and e.get("destination") in NODES and e.get("traffic_level") in TRAFFIC_FACTOR}
            if not valid:
                raise ValueError("Provider response contained no valid network edges")
            for raw in DATA["edges"]:
                update = valid.get((raw[0], raw[1]))
                if update:
                    raw[5] = update["traffic_level"]
                    raw[6] = max(1, float(update.get("current_speed", raw[6])))
            return jsonify({"ok": True, "source": "Live provider", "simulated": False, "updated_at": datetime.utcnow().isoformat() + "Z", "edges": edges()})
        except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError):
            pass
    return jsonify({"ok": True, "source": "Simulation", "simulated": True, "message": "Live traffic unavailable — simulation mode active.", "updated_at": datetime.utcnow().isoformat() + "Z", "edges": edges()})


@app.route("/api/traffic/incident", methods=["POST"])
def traffic_incident_api():
    payload = request.get_json(silent=True) or {}
    severity = str(payload.get("severity", "VERY_HIGH")).upper()
    if severity not in {"HIGH", "VERY_HIGH", "CLOSURE"}: severity = "VERY_HIGH"
    candidates = [e for e in DATA["edges"] if (e[0], e[1]) not in ACTIVE_BLOCKED_EDGES]
    if not candidates: return error("No available road segment for a new incident.", 409)
    source, destination, vehicle = payload.get("source"), payload.get("destination"), payload.get("vehicle", "Car")
    target_path = shortest(source, destination, vehicle) if source in NODES and destination in NODES and source != destination else []
    route_edges = {(e["source"], e["destination"]) for e in target_path}; route_candidates = [e for e in candidates if (e[0], e[1]) in route_edges]
    edge = random.choice(route_candidates or candidates); edge[5] = "VERY_HIGH" if severity == "CLOSURE" else severity
    edge[6] = max(5, round(edge[4] / {"HIGH": 1.9, "VERY_HIGH": 3.0, "CLOSURE": 99.0}[severity], 1))
    blocked = severity == "CLOSURE"
    if blocked: ACTIVE_BLOCKED_EDGES.add((edge[0], edge[1]))
    return jsonify({"ok": True, "message": "Traffic change detected; re-optimization is ready.", "incident": {"source": edge[0], "destination": edge[1], "traffic_level": edge[5], "current_speed": edge[6], "blocked": blocked}, "edges": edges()})


@app.route("/api/traffic/reset", methods=["POST"])
def traffic_reset_api():
    source = json.loads(NETWORK_PATH.read_text(encoding="utf-8")); DATA["edges"] = source["edges"]; ACTIVE_BLOCKED_EDGES.clear()
    return jsonify({"ok": True, "message": "Baseline simulation restored.", "edges": edges()})


@app.route("/api/traffic/summary")
def traffic_summary():
    levels = {level: 0 for level in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")}
    for edge in edges(): levels[edge["traffic_level"]] = levels.get(edge["traffic_level"], 0) + 1
    total = max(1, sum(levels.values()))
    incidents = [{"road": f"{a} → {b}", "type": "Road closure", "severity": "critical"} for a, b in sorted(ACTIVE_BLOCKED_EDGES)]
    return jsonify({"ok": True, "distribution": {k: round(v / total * 100) for k, v in levels.items()}, "incidents": incidents, "active_edges": len(ACTIVE_BLOCKED_EDGES), "source": "Simulation"})




@app.route("/api/benchmark", methods=["POST"])
def benchmark_api():
    payload = request.get_json(silent=True) or {}
    try: scenarios = max(3, min(20, int(payload.get("scenarios", 8))))
    except (TypeError, ValueError): scenarios = 8
    try: seed = int(payload.get("seed", 26137))
    except (TypeError, ValueError): seed = 26137
    return jsonify({"ok": True, **benchmark(scenarios, seed)})


@app.route("/api/qpso/experiment", methods=["POST"])
def qpso_experiment():
    payload = request.get_json(silent=True) or {}
    try: runs, iterations, particles = max(1, min(10, int(payload.get("runs", 3)))), max(5, min(100, int(payload.get("iterations", 35)))), max(4, min(60, int(payload.get("particles", 18))))
    except (TypeError, ValueError): runs, iterations, particles = 3, 35, 18
    public_ids = [n["id"] for n in NODES.values() if n.get("public", True)]
    curves = []
    for seed in range(runs):
        random.seed(seed + 100)
        source, destination = public_ids[seed % len(public_ids)], public_ids[(seed + 3) % len(public_ids)]
        _, best, mean, runtime = qpso(source, destination, "Car", iterations=iterations, particles=particles)
        curves.append({"seed": seed + 100, "best": best, "mean": mean, "runtime_ms": round(runtime, 3), "final_fitness": round(best[-1], 3) if best else None})
    return jsonify({"ok": True, "runs": curves, "parameters": {"runs": runs, "iterations": iterations, "particles": particles}})


@app.route("/api/status")
def status_api():
    live_state = "CONFIGURED" if os.getenv("TRAFFIC_API_URL", "").strip() and os.getenv("TRAFFIC_API_KEY", "").strip() else "SIMULATION MODE"
    return jsonify({"ok": True, "services": [{"name": "Backend API", "state": "ONLINE"}, {"name": "Routing Engine", "state": "ONLINE"}, {"name": "QPSO Engine", "state": "ONLINE"}, {"name": "Traffic Engine", "state": "ONLINE"}, {"name": "Database", "state": "ONLINE"}, {"name": "Live Traffic API", "state": live_state}], "updated_at": datetime.utcnow().isoformat() + "Z"})


@app.route("/api/vrp", methods=["POST"])
def vrp_api():
    if not logged_in(): return error("Login required", 401)
    payload = request.get_json(silent=True) or {}; depot, stops = payload.get("depot"), payload.get("stops", [])
    try: capacity, deadline = float(payload.get("capacity", 20) or 20), float(payload.get("deadline", 0) or 0)
    except (TypeError, ValueError): return error("Capacity and deadline must be numeric.")
    vehicle = payload.get("vehicle", "Car")
    if depot not in NODES or not isinstance(stops, list) or len(stops) < 2: return error("Choose a depot and at least two delivery locations.")
    stops = [s for s in stops if s in NODES and s != depot]
    if len(stops) < 2: return error("At least two valid delivery locations are required.")
    return jsonify({"ok": True, **solve_vrp(depot, stops, vehicle, max(0, capacity), max(0, deadline))})


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"): return error("Endpoint not found.", 404)
    return render_template("404.html", user=current_user()), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "0") == "1")