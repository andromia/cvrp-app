"""TODO: omg refactor pls"""
from typing import List, Tuple
from collections import namedtuple
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import numpy as np

from app.vrp_model import cluster, distance


def get_dropped_nodes(model, assignment) -> List[int]:
    dropped = []
    for idx in range(model.Size()):
        if assignment.Value(model.NextVar(idx)) == idx:
            dropped.append(idx)

    return dropped


def get_solution_str(solution: List) -> str:
    _str = ""

    for i, r in enumerate(solution):
        _str += f"Route(idx={i})\n"
        s = "\n".join("{}: {}".format(*k) for k in enumerate(r))
        _str += s + "\n\n"

    return _str


def solve(
    nodes: List[Tuple[float, float]],
    distance_matrix: List[List[int]],
    time_matrix: List[List[int]],
    time_windows: List[Tuple[int, int]],
    demand: List[int],
    vehicle_caps: List[int],
    depot_index: int,
    constraints: Tuple[int, int, int],
    max_search_seconds: int = 5,
) -> List:
    """
    high level implementation of an ortools capacitated vehicle routing model.

    :nodes:                         list of tuples containing nodes (origin at index 0) with
                                    lat(float), lon(float)
    :distance_matrix:               [[int, int, int, ...], [...] ...] distance matrix of origin
                                    at node 0 and demand nodes at 1 -> len(matrix) - 1 processed
                                    at a known precision
    :demand_quantities:             [int, int, ... len(demand nodes) - 1]
    :vehicle_caps:                      list of integers for vehicle capacity constraint (in demand units)
    :constraints:                   named tuple of "dist_constraint" (int) to use as distance
                                    upper bound
                                    "soft_dist_constraint" (int) for soft upper bound constraint
                                    for vehicle distances
                                    "soft_dist_penalty" (int) for soft upper bound penalty for
                                    exceeding distance constraint
    :max_search_seconds:            int of solve time

    TODO:
    [ ] update with namedtuple usage
    [ ] use nodes list to handle as much as possible
    [ ] handle integer precision entirely
    [ ] refactor into smaller functions
    [ ] refactor with less arg complexity (better arg and config management)
    [ ] add solution type

    """
    NODES = nodes
    DISTANCE_MATRIX = distance_matrix
    NUM_NODES = len(nodes)

    if len(distance_matrix) - 1 == len(demand):
        DEMAND = [0] + list(demand)
    else:
        DEMAND = demand

    # TODO: define a vehicle better
    VEHICLE_CAPS = vehicle_caps
    NUM_VEHICLES = len(VEHICLE_CAPS)
    DEPOT_INDEX = depot_index
    # TODO: can make these per vehicle
    DISTANCE_CONSTRAINT = constraints.dist_constraint
    SOFT_DISTANCE_CONSTRAINT = constraints.soft_dist_constraint
    SOFT_DISTANCE_PENALTY = constraints.soft_dist_penalty
    MAX_SEARCH_SECONDS = max_search_seconds

    manager = pywrapcp.RoutingIndexManager(NUM_NODES, NUM_VEHICLES, depot_index)

    def matrix_callback(i: int, j: int):
        """index of from (i) and to (j)"""
        node_i = manager.IndexToNode(i)
        node_j = manager.IndexToNode(j)
        distance = DISTANCE_MATRIX[node_i][node_j]

        return distance

    def demand_callback(i: int):
        """capacity constraint"""
        demand = DEMAND[manager.IndexToNode(i)]

        return demand

    def time_callback(i: int, j: int):
        """Returns the travel time between the two nodes."""
        node_i = manager.IndexToNode(i)
        node_j = manager.IndexToNode(j)

        return time_matrix[node_i][node_j]

    model = pywrapcp.RoutingModel(manager)

    # demand constraint setup
    model.AddDimensionWithVehicleCapacity(
        # function which return the load at each location (cf. cvrp.py example)
        model.RegisterUnaryTransitCallback(demand_callback),
        0,  # null capacity slack
        VEHICLE_CAPS,  # vehicle maximum capacity
        True,  # start cumul to zero
        "Capacity",
    )

    # distance constraints
    dist_callback_index = model.RegisterTransitCallback(matrix_callback)
    model.SetArcCostEvaluatorOfAllVehicles(dist_callback_index)
    model.AddDimensionWithVehicleCapacity(
        dist_callback_index,
        0,  # 0 slack
        [DISTANCE_CONSTRAINT for i in range(NUM_VEHICLES)],
        True,  # start to zero
        "Distance",
    )

    dst_dim = model.GetDimensionOrDie("Distance")
    for i in range(manager.GetNumberOfVehicles()):
        end_idx = model.End(i)
        dst_dim.SetCumulVarSoftUpperBound(
            end_idx, SOFT_DISTANCE_CONSTRAINT, SOFT_DISTANCE_PENALTY
        )

    # time windows constraint
    transit_callback_index = model.RegisterTransitCallback(time_callback)
    model.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    model.AddDimension(
        transit_callback_index,
        30,  # allow waiting time
        30,  # maximum time per vehicle
        False,  # Don't force start cumul to zero.
        "Time",
    )

    time_dimension = model.GetDimensionOrDie("Time")
    # Add time window constraints for each location except depot.
    for location_idx, time_window in enumerate(time_windows):
        if location_idx == 0:
            continue
        index = manager.NodeToIndex(location_idx)
        time_dimension.CumulVar(index).SetRange(time_window[0], time_window[1])

    # Add time window constraints for each vehicle start node.
    for vehicle_id in range(NUM_VEHICLES):
        index = model.Start(vehicle_id)
        time_dimension.CumulVar(index).SetRange(time_windows[0][0], time_windows[0][1])

    for i in range(NUM_VEHICLES):
        model.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(model.Start(i)))
        model.AddVariableMinimizedByFinalizer(time_dimension.CumulVar(model.End(i)))

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.time_limit.seconds = MAX_SEARCH_SECONDS

    assignment = model.SolveWithParameters(search_parameters)

    if assignment:

        STOP_TYPE = Tuple[int, float, float, int, float]
        Stop = namedtuple("Stop", ["idx", "lat", "lon", "demand", "dist"])

        solution = []
        for _route_number in range(model.vehicles()):
            route = []
            idx = model.Start(_route_number)

            if model.IsEnd(assignment.Value(model.NextVar(idx))):
                continue

            else:
                prev_node_index = manager.IndexToNode(idx)

                while True:

                    # TODO: time_var = time_dimension.CumulVar(order)
                    node_index = manager.IndexToNode(idx)
                    original_idx = NODES[node_index]["idx"]
                    lat = NODES[node_index]["lat"]
                    lon = NODES[node_index]["lon"]

                    demand = DEMAND[node_index]
                    dist = DISTANCE_MATRIX[prev_node_index][node_index]

                    route.append(Stop(original_idx, lat, lon, demand, dist))

                    if model.IsEnd(idx):
                        break

                    prev_node = node_index
                    idx = assignment.Value(model.NextVar(idx))

            solution.append(route)

        return solution


def create_vehicles(
    origin_lat: float,
    origin_lon: float,
    dest_lats: List[float],
    dest_lons: List[float],
    demand_quantities: List[int],
    max_vehicle_capacity: int = 26,
) -> dict:  # TODO: tune in ortools-pyinteractive
    # demand including origin (ortools required)
    if len(demand_quantities) == len(dest_lats):
        ALL_DEMAND: List[int] = [0] + demand_quantities
    else:
        ALL_DEMAND: List[int] = demand_quantities

    # ad-hoc dynamic solve time TODO: utilize unique clusters and sizes, etc.
    if len(ALL_DEMAND) - 1 > 250:
        MAX_SEARCH_SECONDS: int = 120
    elif len(ALL_DEMAND) - 1 > 200 and len(ALL_DEMAND) - 1 <= 250:
        MAX_SEARCH_SECONDS: int = 60
    elif len(ALL_DEMAND) - 1 > 150 and len(ALL_DEMAND) - 1 <= 200:
        MAX_SEARCH_SECONDS: int = 30
    else:
        MAX_SEARCH_SECONDS: int = 5

    INT_PRECISION = 100
    MAX_VEHICLE_DIST = 3500 * INT_PRECISION
    MAX_VEHICLE_CAP: int = max_vehicle_capacity
    NUM_VEHICLES: int = len(ALL_DEMAND)
    SOFT_MAX_VEHICLE_DIST: int = int(MAX_VEHICLE_DIST * 0.75)
    SOFT_MAX_VEHICLE_COST: int = MAX_VEHICLE_DIST + 1  # cost feels ambiguous

    VEHICLE_CAPACITIES: List[int] = [MAX_VEHICLE_CAP for i in range(NUM_VEHICLES)]

    DIST_MATRIX: List[List[int]] = distance.create_matrix(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dest_lats=dest_lats,
        dest_lons=dest_lons,
        int_precision=INT_PRECISION,
    )

    TIME_MATRIX: List[List[int]] = (
        (np.array(DIST_MATRIX) / 440 / INT_PRECISION).round(0).astype(int)
    )
    TIME_WINDOWS: List[Tuple[int, int]] = [(0, 23)] * len(DIST_MATRIX)

    CLUSTERS: List[int] = cluster.create_dbscan_clusters(lats=dest_lats, lons=dest_lons)

    CONSTRAINTS_TYPE = Tuple[int, int, int]
    Constraints: CONSTRAINTS_TYPE = namedtuple(
        "Constraint", ["dist_constraint", "soft_dist_constraint", "soft_dist_penalty"]
    )
    CONSTRAINTS: CONSTRAINTS_TYPE = Constraints(
        dist_constraint=MAX_VEHICLE_DIST,
        soft_dist_constraint=SOFT_MAX_VEHICLE_DIST,
        soft_dist_penalty=SOFT_MAX_VEHICLE_COST,
    )

    NODES_ARR: np.ndarray = np.array(
        [(0, origin_lat, origin_lon)]
        + list(zip(list(range(1, len(ALL_DEMAND) + 1)), dest_lats, dest_lons)),
        dtype=[("idx", int), ("lat", float), ("lon", float)],
    )

    DIST_MATRIX_ARR: np.ndarray = np.array(DIST_MATRIX)
    WINDOWS_MATRIX_ARR: np.ndarray = np.array(TIME_MATRIX)
    WINDOWS_ARR: np.ndarray = np.array(TIME_WINDOWS, dtype=object)
    DEMAND_ARR: np.ndarray = np.array(ALL_DEMAND)
    VEHICLE_CAP_ARR: np.ndarray = np.array(VEHICLE_CAPACITIES)

    # preprocess exceptions based on MAX_VEHICLE_DIST
    EXCEPTIONS = np.where(DIST_MATRIX_ARR[0] > MAX_VEHICLE_DIST)

    vehicle_count = 0
    vehicle_ids = [None] * len(dest_lats)
    stop_nums = [None] * len(dest_lats)
    for i, c in enumerate(np.unique(CLUSTERS)):

        # align with matrix
        is_cluster = np.where(CLUSTERS == c)[0]
        is_cluster = is_cluster + 1
        is_cluster = np.insert(is_cluster, 0, 0)
        is_cluster = is_cluster[~np.isin(is_cluster, EXCEPTIONS)]

        solution = solve(
            nodes=NODES_ARR[is_cluster],
            distance_matrix=DIST_MATRIX_ARR[is_cluster],
            time_matrix=WINDOWS_MATRIX_ARR[is_cluster],
            time_windows=WINDOWS_ARR[is_cluster],
            demand=DEMAND_ARR[is_cluster],
            vehicle_caps=VEHICLE_CAP_ARR[is_cluster],
            depot_index=0,
            constraints=CONSTRAINTS,
            max_search_seconds=MAX_SEARCH_SECONDS,
        )

        if not solution:
            continue

        for vehicle in solution:
            vehicle_count += 1

            for n, stop in enumerate(vehicle):
                if stop.idx != 0:
                    vehicle_ids[stop.idx - 1] = vehicle_count
                    stop_nums[stop.idx - 1] = n

    return {"id": vehicle_ids, "stops": stop_nums}
