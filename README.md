# QI-Traffic Professional

QI-Traffic is a Flask-based intelligent transportation decision-support platform for a selected Hyderabad urban study area. It combines a weighted directed road graph, simulated traffic conditions, Dijkstra, A*, discrete quantum-inspired particle swarm optimization (QPSO), vehicle routing, benchmarking, and what-if incident re-optimization in one operations-center experience.

> **Important:** QPSO runs on classical computing infrastructure. The application does not claim to be a quantum computer, a complete Hyderabad road network, or a live traffic-control system.

## Features

The product view includes a map-first route optimizer, measured comparison of Dijkstra/A*/QPSO, alternative route cards, traffic intelligence, incident simulation, automatic re-optimization, VRP planning, emergency optimization mode, network explorer, service status, benchmark lab, convergence experiments, and a mathematical model page. The dashboard map has a real-time refresh stream with configurable 10/20/30 second cadence, last-update timestamp, live/simulation source badge, and incident markers.

The application deliberately does not request browser geolocation. Users manually select origin and destination. Traffic is labeled **Simulation** unless a future provider integration is configured.

## Architecture

`app.py` exposes HTML views and JSON APIs. `routing.py` contains the graph model, Dijkstra, A*, alternative route generation, QPSO, risk scoring, mathematical model, and benchmarks. `vrp.py` contains capacity-constrained delivery planning. `database.py` initializes the local SQLite authentication and result schema. `templates/` and `static/` implement the responsive operations-center interface.

## Technology stack

Python 3.11+, Flask, SQLite, local graph logic, Leaflet, OpenStreetMap tiles, optional public OSRM geometry, Chart.js, and vanilla JavaScript. No React, Docker, cloud infrastructure, or paid API is required for the basic launch.

## Installation and running

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
cp .env.example .env            # optional
python app.py
```

Open `http://127.0.0.1:5000`. Demo users are `admin/admin123`, `user/user123`, and `emergency/emergency123`; change these before production use.

## Environment variables

See `.env.example`. `FLASK_SECRET_KEY` changes the session signing key, `FLASK_DEBUG` controls debug mode, `PORT` changes the listening port, and `TRAFFIC_API_KEY` / `MAP_API_KEY` are reserved for a legitimate provider integration. `TRAFFIC_API_URL` optionally enables the generic live traffic adapter. It must return `{"edges":[{"source","destination","traffic_level","current_speed"}]}` and is protected by the API key. No secrets are stored in the repository.

## Data sources and limitations

The local `data/network.json` dataset contains Hyderabad landmark anchors plus synthetic junctions for a scalable demonstration graph. The UI calls this a **selected study area**, not the complete Hyderabad road network. OpenStreetMap is used for the basemap. OSRM may be queried by the browser for road-following geometry; if unavailable, the UI falls back to node-to-node geometry. Without a configured external provider, the real-time map refreshes the current simulated snapshot and explicitly displays **Simulation**; it never pretends simulated traffic is live.

## Algorithms and research view

Dijkstra provides an exact shortest path for the configured edge weights. A* uses a geographic lower-bound heuristic. QPSO performs stochastic discrete route exploration with best-so-far and swarm-mean convergence curves, configurable population/iteration parameters in the analytics page, and measured runtime. Benchmarks report scenario-level distance, time, fitness, feasibility, and runtime; they do not assert universal superiority.

The objective is `min F = wt*T + wd*D + wc*C + wl*Pdeadline`. Constraints cover path continuity, vehicle restrictions, closed roads, VRP capacity, flow conservation, and optional deadlines.

## Traffic modes and What-If simulation

The dashboard supports normal traffic, random traffic, morning peak, evening peak, heavy congestion, severe congestion incidents, and road closure events. An incident changes the active in-memory graph, reports the affected edge, and triggers a fresh route comparison. Restore baseline resets the local simulation state. The `/api/traffic/live` endpoint polls the configured provider when both `TRAFFIC_API_URL` and `TRAFFIC_API_KEY` are present; timeouts or malformed responses fall back safely to the labeled simulation snapshot.

## API highlights

`GET /api/network`, `POST /api/route`, `GET|POST /api/traffic`, `POST /api/traffic/incident`, `POST /api/traffic/reset`, `GET /api/traffic/summary`, `POST /api/benchmark`, `POST /api/qpso/experiment`, `POST /api/vrp`, `GET /api/model`, and `GET /api/status`.

## Future enhancements

A production deployment could ingest a validated OSMnx extract, connect a legitimate traffic provider through environment variables, persist route/incident/optimization runs, add background job execution for very large QPSO experiments, and apply organization-grade authentication and audit controls.
