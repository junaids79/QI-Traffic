from __future__ import annotations

from itertools import permutations
from routing import NODES, shortest, metrics, fitness


def _demand(node_id: str) -> float:
    typ = NODES[node_id].get("place_type", "")
    return {"Hospital": 3, "Shopping Mall": 5, "University": 4, "IT Hub": 4, "Historical Landmark": 2}.get(typ, 3)


def _build_route(depot, order, vehicle):
    route_nodes=[depot]
    path=[]
    current=depot
    for stop in order:
        segment=shortest(current,stop,vehicle)
        if not segment: return None
        path.extend(segment); route_nodes.append(stop); current=stop
    back=shortest(current,depot,vehicle)
    if not back: return None
    path.extend(back); route_nodes.append(depot)
    return route_nodes,path


def _validate_flow(route_nodes, path, depot):
    if not route_nodes or route_nodes[0]!=depot or route_nodes[-1]!=depot or not path:
        return False
    prev=depot
    for edge in path:
        if edge["source"]!=prev: return False
        prev=edge["destination"]
    return prev==depot


def solve_vrp(depot, stops, vehicle="Car", capacity=20.0, deadline=0.0):
    demands={stop:_demand(stop) for stop in stops}
    total_demand=sum(demands.values())
    if total_demand>capacity:
        return {"feasible":False,"error":f"Capacity constraint violated: demand {total_demand} exceeds vehicle capacity {capacity}.","demands":demands}

    # Greedy nearest-feasible construction.
    remaining=set(stops); order=[]; current=depot
    while remaining:
        candidates=[]
        for stop in remaining:
            segment=shortest(current,stop,vehicle)
            if segment:
                candidates.append((metrics(segment)[1],stop))
        if not candidates: break
        _, chosen=min(candidates)
        order.append(chosen); remaining.remove(chosen); current=chosen

    built=_build_route(depot,order,vehicle) if not remaining else None
    if built is None:
        return {"feasible":False,"error":"No feasible route satisfies graph connectivity/vehicle restrictions.","demands":demands}
    route_nodes,path=built
    distance,travel_time,congestion=metrics(path)
    deadline_met=(deadline<=0 or travel_time<=deadline)

    # Small-instance exact reference: enumerate stop orderings and select minimum objective.
    exact=None
    if len(stops)<=7:
        best=None
        for perm in permutations(stops):
            candidate=_build_route(depot,perm,vehicle)
            if not candidate: continue
            rn,pp=candidate
            if not _validate_flow(rn,pp,depot): continue
            score=fitness(pp,deadline)
            if best is None or score<best[0]: best=(score,rn,pp)
        if best:
            ex_score,ex_nodes,ex_path=best
            ed,et,ec=metrics(ex_path)
            exact={"route":ex_nodes,"distance":round(ed,2),"travel_time":round(et,2),"fitness":round(ex_score,2),"congestion":round(ec,2),"method":"Exact permutation reference (small VRP instance)"}

    return {
        "feasible":True,
        "method":"Capacity-constrained greedy VRP",
        "vehicle":vehicle,
        "depot":depot,
        "stops":stops,
        "demands":demands,
        "capacity":capacity,
        "total_demand":total_demand,
        "route":route_nodes,
        "distance":round(distance,2),
        "travel_time":round(travel_time,2),
        "congestion":round(congestion,2),
        "deadline":deadline,
        "deadline_met":deadline_met,
        "flow_constraints_satisfied":_validate_flow(route_nodes,path,depot),
        "capacity_constraint_satisfied":total_demand<=capacity,
        "time_window_satisfied":deadline_met,
        "exact_reference":exact,
        "note":"Demands are prototype values derived from destination type; replace with operational demand data for production use."
    }
