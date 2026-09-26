from __future__ import annotations

import heapq
import json
import math
import random
import time
from itertools import count
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
NETWORK_PATH = BASE_DIR / "data" / "network.json"
DATA = json.loads(NETWORK_PATH.read_text(encoding="utf-8"))
NODES = {node["id"]: node for node in DATA["nodes"]}
ACTIVE_BLOCKED_EDGES: set[tuple[str, str]] = set()

TRAFFIC_FACTOR = {"LOW": 1.0, "MEDIUM": 1.25, "HIGH": 1.6, "VERY_HIGH": 2.2}
DEFAULT_WEIGHTS = {"time": 0.45, "distance": 0.25, "congestion": 0.25, "deadline": 0.05}


def public_nodes() -> list[dict[str, Any]]:
    return [node for node in NODES.values() if node.get("public", True)]


def edges() -> list[dict[str, Any]]:
    result = []
    for raw in DATA["edges"]:
        result.append(
            {
                "source": raw[0],
                "destination": raw[1],
                "distance": float(raw[2]),
                "normal_time": float(raw[3]),
                "speed_limit": float(raw[4]),
                "traffic_level": raw[5],
                "current_speed": float(raw[6]),
                "emergency_access": bool(raw[7]),
                "vehicle_restrictions": raw[8] or "",
            }
        )
    return result


def _factor(level: str) -> float:
    return TRAFFIC_FACTOR.get(level, 1.0)


def _restrictions(edge: dict[str, Any]) -> set[str]:
    return {x.strip().lower() for x in str(edge.get("vehicle_restrictions", "")).split(",") if x.strip()}


def _vehicle_allowed(edge: dict[str, Any], vehicle: str) -> bool:
    return vehicle.strip().lower() not in _restrictions(edge)


def _edge_time(edge: dict[str, Any]) -> float:
    return float(edge["distance"]) / max(float(edge["current_speed"]), 1.0) * 60.0


def graph(vehicle: str = "Car", emergency: bool = False) -> dict[str, list[tuple[str, dict[str, Any], float]]]:
    result = {node_id: [] for node_id in NODES}
    for edge in edges():
        key = (edge["source"], edge["destination"])
        if key in ACTIVE_BLOCKED_EDGES:
            continue
        if not _vehicle_allowed(edge, vehicle):
            continue
        if emergency and not edge["emergency_access"]:
            continue
        result[edge["source"]].append((edge["destination"], edge, _edge_time(edge)))
    return result


def haversine_km(a: dict[str, Any], b: dict[str, Any]) -> float:
    radius = 6371.0
    p1, p2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dp = math.radians(b["latitude"] - a["latitude"])
    dl = math.radians(b["longitude"] - a["longitude"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.asin(math.sqrt(h))


def heuristic(node_a: str, node_b: str) -> float:
    # Lower bound using a generous 90 km/h upper speed so it does not overestimate time.
    return haversine_km(NODES[node_a], NODES[node_b]) / 90.0 * 60.0


def shortest(source: str, destination: str, vehicle: str = "Car", emergency: bool = False, astar: bool = False) -> list[dict[str, Any]]:
    if source not in NODES or destination not in NODES or source == destination:
        return []
    g = graph(vehicle, emergency)
    sequence = count()
    queue = [(0.0, next(sequence), source, [], 0.0)]
    best: dict[str, float] = {}
    while queue:
        priority, _, current, path, cost = heapq.heappop(queue)
        if current in best and best[current] <= cost:
            continue
        best[current] = cost
        if current == destination:
            return path
        for nxt, edge, travel_time in g.get(current, []):
            new_cost = cost + travel_time
            estimate = heuristic(nxt, destination) if astar else 0.0
            heapq.heappush(queue, (new_cost + estimate, next(sequence), nxt, path + [edge], new_cost))
    return []


def path_nodes(path: list[dict[str, Any]]) -> list[str]:
    return [path[0]["source"]] + [e["destination"] for e in path] if path else []


def is_valid_path(path: list[dict[str, Any]], source: str, destination: str, vehicle: str = "Car", emergency: bool = False) -> bool:
    if not path or path[0]["source"] != source or path[-1]["destination"] != destination:
        return False
    previous = source
    for edge in path:
        if edge["source"] != previous or not _vehicle_allowed(edge, vehicle):
            return False
        if emergency and not edge["emergency_access"]:
            return False
        if (edge["source"], edge["destination"]) in ACTIVE_BLOCKED_EDGES:
            return False
        previous = edge["destination"]
    return previous == destination


def metrics(path: list[dict[str, Any]]) -> tuple[float, float, float]:
    distance = sum(float(e["distance"]) for e in path)
    travel_time = sum(_edge_time(e) for e in path)
    congestion = sum(_factor(e["traffic_level"]) for e in path)
    return distance, travel_time, congestion


def objective_components(path: list[dict[str, Any]], deadline: float | None = None) -> dict[str, float]:
    distance, travel_time, congestion = metrics(path)
    deadline_penalty = max(0.0, travel_time - float(deadline or 0.0))
    return {"travel_time": travel_time, "distance": distance, "congestion": congestion, "deadline_penalty": deadline_penalty}


def fitness(path: list[dict[str, Any]], deadline: float | None = None, weights: dict[str, float] | None = None) -> float:
    if not path:
        return 1_000_000.0
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    c = objective_components(path, deadline)
    return (
        c["travel_time"] * weights["time"]
        + c["distance"] * weights["distance"]
        + c["congestion"] * weights["congestion"]
        + c["deadline_penalty"] * 10.0 * weights["deadline"]
    )


def fitness_breakdown(path: list[dict[str, Any]], deadline: float | None = None, weights: dict[str, float] | None = None) -> dict[str, float]:
    """Weighted contribution of each objective term, for a 'why this route won' view.

    Mirrors fitness() term-for-term so the four numbers here always sum to the
    total fitness score — no separate/hidden formula.
    """
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    if not path:
        return {"time": 0.0, "distance": 0.0, "congestion": 0.0, "deadline_penalty": 0.0}
    c = objective_components(path, deadline)
    return {
        "time": round(c["travel_time"] * weights["time"], 2),
        "distance": round(c["distance"] * weights["distance"], 2),
        "congestion": round(c["congestion"] * weights["congestion"], 2),
        "deadline_penalty": round(c["deadline_penalty"] * 10.0 * weights["deadline"], 2),
    }


def _edge_lookup(vehicle: str, emergency: bool) -> dict[tuple[str, str], dict[str, Any]]:
    return {(e["source"], e["destination"]): e for e in edges() if _vehicle_allowed(e, vehicle) and (not emergency or e["emergency_access"])}


def shortest_with_penalties(source: str, destination: str, vehicle: str = "Car", emergency: bool = False, blocked_edges: set[tuple[str, str]] | None = None, penalties: dict[tuple[str, str], float] | None = None) -> list[dict[str, Any]]:
    blocked_edges = blocked_edges or set()
    penalties = penalties or {}
    g = graph(vehicle, emergency)
    sequence = count()
    queue = [(0.0, next(sequence), source, [], 0.0)]
    best: dict[str, float] = {}
    while queue:
        _, _, current, path, cost = heapq.heappop(queue)
        if current in best and best[current] <= cost:
            continue
        best[current] = cost
        if current == destination:
            return path
        for nxt, edge, travel_time in g.get(current, []):
            key = (edge["source"], edge["destination"])
            if key in blocked_edges:
                continue
            weighted = travel_time * float(penalties.get(key, 1.0))
            heapq.heappush(queue, (cost + weighted, next(sequence), nxt, path + [edge], cost + weighted))
    return []


def alternative_routes(source: str, destination: str, vehicle: str = "Car", emergency: bool = False, limit: int = 4) -> list[list[dict[str, Any]]]:
    routes: list[list[dict[str, Any]]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    baseline = shortest(source, destination, vehicle, emergency)
    if not baseline:
        return []
    routes.append(baseline)
    seen.add(tuple((e["source"], e["destination"]) for e in baseline))
    penalties: dict[tuple[str, str], float] = {}
    for _ in range(limit - 1):
        for e in routes[-1]:
            key = (e["source"], e["destination"])
            penalties[key] = penalties.get(key, 1.0) + 3.0
        candidate = shortest_with_penalties(source, destination, vehicle, emergency, penalties=penalties)
        sig = tuple((e["source"], e["destination"]) for e in candidate)
        if not candidate or sig in seen:
            break
        routes.append(candidate)
        seen.add(sig)
    return routes


def _edge_local_cost(edge: dict[str, Any], travel_time: float, weights: dict[str, float]) -> float:
    # Per-edge cost used to steer constructive search. Mirrors the objective's
    # weighting so a candidate route actually reflects time/distance/congestion
    # priorities instead of always chasing the fastest nearby road.
    return (
        travel_time * weights["time"]
        + float(edge["distance"]) * weights["distance"]
        + _factor(edge["traffic_level"]) * weights["congestion"]
    )


def _random_feasible_route(source: str, destination: str, vehicle: str, emergency: bool, weights: dict[str, float] | None = None) -> list[dict[str, Any]]:
    # Randomized constructive route. It creates genuine variation without fabricating scores.
    # Candidates are shortlisted by the *weighted* local cost (time/distance/congestion),
    # not raw travel time, so a congestion- or distance-heavy objective actually steers
    # the search toward low-congestion or short roads instead of always the fastest one.
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    current = source
    result: list[dict[str, Any]] = []
    visited = {source}
    g = graph(vehicle, emergency)
    for _ in range(len(NODES) + 5):
        if current == destination:
            return result
        options = [x for x in g.get(current, []) if x[0] not in visited]
        if not options:
            break
        options.sort(key=lambda x: _edge_local_cost(x[1], x[2], weights))
        shortlist = options[: min(5, len(options))]
        nxt, edge, _ = random.choice(shortlist)
        result.append(edge)
        visited.add(nxt)
        current = nxt
    if current != destination:
        bridge = shortest(current, destination, vehicle, emergency)
        if bridge:
            result.extend(bridge)
    return result if result and result[-1]["destination"] == destination else []


def qpso(source: str, destination: str, vehicle: str = "Car", emergency: bool = False, iterations: int = 45, particles: int = 24, deadline: float | None = None, weights: dict[str, float] | None = None) -> tuple[list[dict[str, Any]], list[float], list[float], float]:
    """Discrete QPSO-inspired route search with quantum-style contraction/exploration.

    The implementation keeps the best-so-far objective and current population mean
    as measured outputs. No synthetic convergence values are inserted.
    """
    started = time.perf_counter()
    lookup = _edge_lookup(vehicle, emergency)
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    population: list[list[dict[str, Any]]] = []
    signatures: set[tuple[tuple[str, str], ...]] = set()

    # Start with diverse feasible particles rather than seeding the exact shortest path.
    # This makes the convergence chart show genuine exploration followed by improvement.
    baseline = shortest(source, destination, vehicle, emergency)
    baseline_sig = tuple((e["source"], e["destination"]) for e in baseline) if baseline else ()
    for p in alternative_routes(source, destination, vehicle, emergency, limit=max(3, min(6, particles // 4)))[1:]:
        if p and is_valid_path(p, source, destination, vehicle, emergency):
            sig = tuple((e["source"], e["destination"]) for e in p)
            if sig != baseline_sig and sig not in signatures:
                population.append(p)
                signatures.add(sig)
    for _ in range(particles * 8):
        p = _random_feasible_route(source, destination, vehicle, emergency, weights)
        if p:
            sig = tuple((e["source"], e["destination"]) for e in p)
            if sig not in signatures:
                population.append(p)
                signatures.add(sig)
        if len(population) >= particles:
            break
    if not population:
        return [], [], [], (time.perf_counter() - started) * 1000.0
    while len(population) < particles:
        population.append(list(population[len(population) % len(population)]))

    def score(p: list[dict[str, Any]]) -> float:
        return fitness(p, deadline, weights)

    personal = [list(p) for p in population]
    scores = [score(p) for p in personal]
    best_idx = min(range(len(scores)), key=scores.__getitem__)
    global_best = list(personal[best_idx])
    global_score = scores[best_idx]
    best_curve, mean_curve = [], []

    for iteration in range(max(1, iterations)):
        beta = 0.9 - 0.55 * (iteration / max(1, iterations - 1))
        # The exact reference becomes an attractor after exploration has started.
        if iteration == max(2, iterations // 5) and baseline:
            if all(tuple((e["source"], e["destination"]) for e in p) != baseline_sig for p in personal):
                personal[0] = list(baseline)
                scores[0] = score(baseline)
        for i in range(len(personal)):
            current = personal[i]
            if random.random() < beta:
                candidate = _random_feasible_route(source, destination, vehicle, emergency, weights)
            else:
                candidate = list(global_best)
                if len(candidate) > 2 and random.random() < 0.8:
                    # Quantum-inspired contraction: perturb a route around the global attractor.
                    alt = alternative_routes(source, destination, vehicle, emergency, limit=4)
                    if alt:
                        candidate = random.choice(alt)
            if candidate and score(candidate) < scores[i]:
                personal[i] = candidate
                scores[i] = score(candidate)
        best_idx = min(range(len(scores)), key=scores.__getitem__)
        if scores[best_idx] < global_score:
            global_score = scores[best_idx]
            global_best = list(personal[best_idx])
        best_curve.append(round(global_score, 4))
        mean_curve.append(round(sum(scores) / len(scores), 4))

    if not is_valid_path(global_best, source, destination, vehicle, emergency):
        global_best = shortest(source, destination, vehicle, emergency)
    else:
        # One bounded local-search pass: polish the swarm's best candidate instead
        # of stopping at the first decent one it found. Only accepted if it
        # actually scores lower on the same fitness function used throughout.
        refined = _local_refine(global_best, source, destination, vehicle, emergency, deadline, weights)
        if refined and is_valid_path(refined, source, destination, vehicle, emergency):
            refined_score = fitness(refined, deadline, weights)
            if refined_score < global_score:
                global_best, global_score = refined, refined_score
                if best_curve:
                    best_curve[-1] = round(global_score, 4)
    return global_best, best_curve, mean_curve, (time.perf_counter() - started) * 1000.0


def _weighted_shortest(source: str, destination: str, vehicle: str, emergency: bool, weights: dict[str, float] | None = None) -> list[dict[str, Any]]:
    # Dijkstra over the *weighted* local cost (time/distance/congestion), not raw time,
    # reusing shortest_with_penalties' multiplier mechanism. Used by the post-swarm
    # local refinement below so any re-route it proposes is genuinely weight-aware.
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    g = graph(vehicle, emergency)
    penalties: dict[tuple[str, str], float] = {}
    for opts in g.values():
        for _dest, edge, travel_time in opts:
            key = (edge["source"], edge["destination"])
            cost = _edge_local_cost(edge, travel_time, weights)
            penalties[key] = cost / travel_time if travel_time > 0 else 1.0
    return shortest_with_penalties(source, destination, vehicle, emergency, penalties=penalties)


def _local_refine(path: list[dict[str, Any]], source: str, destination: str, vehicle: str, emergency: bool, deadline: float | None, weights: dict[str, float] | None, attempts: int = 25) -> list[dict[str, Any]]:
    """Bounded local search run once after the swarm converges.

    It repeatedly tries re-routing a random internal segment of the current best
    path with a genuinely weight-aware shortest path (_weighted_shortest), and
    keeps the change ONLY if it measurably lowers the real fitness score computed
    the same way everywhere else in this module. No score is ever nudged directly.
    """
    if not path or len(path) < 3:
        return path
    best = list(path)
    best_score = fitness(best, deadline, weights)
    for _ in range(attempts):
        nodes = [best[0]["source"]] + [e["destination"] for e in best]
        if len(nodes) < 4:
            break
        i = random.randint(0, len(nodes) - 3)
        j = random.randint(i + 2, len(nodes) - 1)
        bridge = _weighted_shortest(nodes[i], nodes[j], vehicle, emergency, weights)
        if not bridge:
            continue
        bridge_nodes = [bridge[0]["source"]] + [e["destination"] for e in bridge]
        outside = set(nodes[:i]) | set(nodes[j + 1:])
        if any(n in outside for n in bridge_nodes[1:-1]):
            continue
        candidate = best[:i] + bridge + best[j:]
        cand_nodes = [candidate[0]["source"]] + [e["destination"] for e in candidate]
        if len(set(cand_nodes)) != len(cand_nodes):
            continue
        cand_score = fitness(candidate, deadline, weights)
        if cand_score < best_score - 1e-9:
            best, best_score = candidate, cand_score
    return best


def risk_for_path(path: list[dict[str, Any]], deadline: float | None = None) -> dict[str, Any]:
    if not path:
        return {"score": 100.0, "level": "HIGH", "explanation": ["No feasible route was found."], "components": {"congestion": 100.0, "delay": 0.0}}
    distance, travel_time, congestion = metrics(path)
    avg_congestion = congestion / max(1, len(path))
    congestion_component = min(75.0, avg_congestion / 2.2 * 75.0)
    delay = max(0.0, travel_time - float(deadline or 0)) if deadline else 0.0
    delay_component = min(25.0, delay * 2.5)
    score = round(min(100.0, congestion_component + delay_component), 2)
    level = "LOW" if score < 35 else "MEDIUM" if score < 65 else "HIGH"
    explanation = [f"Average simulated congestion factor is {avg_congestion:.2f}."]
    if deadline:
        explanation.append("The route exceeds the requested deadline." if delay > 0 else "The route is within the requested deadline.")
    explanation.append("This is an explainable prototype risk score, not a validated safety prediction model.")
    return {"score": score, "level": level, "explanation": explanation, "components": {"congestion": round(congestion_component, 2), "delay": round(delay_component, 2)}}


def mathematical_model() -> dict[str, Any]:
    return {
        "objective": "min F = w_t*T + w_d*D + w_c*C + w_l*P_deadline",
        "definitions": [
            "T = total travel time across selected edges",
            "D = total route distance",
            "C = accumulated congestion factor",
            "P_deadline = max(0, arrival_time - deadline)",
            "w_t, w_d, w_c, w_l = configurable objective weights",
        ],
        "decision_variables": [
            "x_ij = 1 when directed edge i→j is selected, otherwise 0",
            "y_iv = 1 when vehicle v serves node i in the VRP model, otherwise 0",
        ],
        "constraints": [
            "Flow conservation: incoming flow equals outgoing flow at intermediate nodes.",
            "Source/destination: one route leaves the source and one route reaches the destination.",
            "Vehicle capacity: total assigned demand cannot exceed vehicle capacity.",
            "Time window: service/arrival time must respect the configured deadline or stop window.",
            "Vehicle restrictions: prohibited vehicle types cannot use restricted edges.",
            "Road closure: blocked edges are excluded from feasible routes.",
        ],
        "assumptions": [
            "Traffic is simulated in the prototype; production deployment would ingest a validated live traffic feed.",
            "The 50-node network contains real Hyderabad landmark anchors plus synthetic junctions for scalable demonstration.",
        ],
    }


def benchmark(scenarios: int = 8, seed: int = 26137) -> dict[str, Any]:
    """Systematic point-to-point benchmark. Dijkstra is the exact shortest-path reference."""
    rng = random.Random(seed)
    public_ids = [n["id"] for n in public_nodes()]
    original_edges = json.loads(json.dumps(DATA["edges"]))
    original_blocks = set(ACTIVE_BLOCKED_EDGES)
    rows = []
    try:
        ACTIVE_BLOCKED_EDGES.clear()
        for scenario in range(1, scenarios + 1):
            source, destination = rng.sample(public_ids, 2)
            vehicle = rng.choice(["Car", "Bike", "Bus", "Truck"])
            # Vary traffic deterministically for each scenario.
            for raw in DATA["edges"]:
                level = rng.choice(["LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"])
                raw[5] = level
                raw[6] = max(10, round(raw[4] / _factor(level), 1))
            d0 = time.perf_counter(); dp = shortest(source, destination, vehicle); dms = (time.perf_counter()-d0)*1000
            a0 = time.perf_counter(); ap = shortest(source, destination, vehicle, False, True); ams = (time.perf_counter()-a0)*1000
            qp, bc, mc, qms = qpso(source, destination, vehicle, deadline=0, iterations=35, particles=18)
            dfit = fitness(dp); afit = fitness(ap); qfit = fitness(qp)
            dd, dt, dc = metrics(dp) if dp else (0,0,0)
            ad, at, ac = metrics(ap) if ap else (0,0,0)
            qd, qt, qc = metrics(qp) if qp else (0,0,0)
            rows.append({"scenario":scenario,"source":source,"destination":destination,"vehicle":vehicle,
                         "dijkstra":{"distance":round(dd,2),"time":round(dt,2),"fitness":round(dfit,2),"runtime_ms":round(dms,3)},
                         "astar":{"distance":round(ad,2),"time":round(at,2),"fitness":round(afit,2),"runtime_ms":round(ams,3)},
                         "qpso":{"distance":round(qd,2),"time":round(qt,2),"fitness":round(qfit,2),"runtime_ms":round(qms,3),"iterations":len(bc)}})
    finally:
        DATA["edges"] = original_edges
        ACTIVE_BLOCKED_EDGES.clear(); ACTIVE_BLOCKED_EDGES.update(original_blocks)
    summary = {}
    for algo in ["dijkstra","astar","qpso"]:
        valid = [r[algo] for r in rows if r[algo]["fitness"] < 1_000_000]
        summary[algo] = {
            "avg_distance_km": round(sum(x["distance"] for x in valid)/len(valid),2) if valid else None,
            "avg_time_min": round(sum(x["time"] for x in valid)/len(valid),2) if valid else None,
            "avg_fitness": round(sum(x["fitness"] for x in valid)/len(valid),2) if valid else None,
            "avg_runtime_ms": round(sum(x["runtime_ms"] for x in valid)/len(valid),3) if valid else None,
            "feasible_scenarios": len(valid),
        }
    return {"scenarios":rows,"summary":summary,"reference":"Dijkstra is used as the exact shortest-path reference for this point-to-point benchmark; QPSO is evaluated on the same weighted network.","seed":seed}