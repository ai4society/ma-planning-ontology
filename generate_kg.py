from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, XSD, RDFS
import json
import argparse

# Helper functions for creating structured individuals
def create_grid_location(g, ma_ns, x, y):
    loc_node = BNode()
    g.add((loc_node, RDF.type, ma_ns.GridLocation))
    g.add((loc_node, ma_ns.xCoordinate, Literal(x, datatype=XSD.integer)))
    g.add((loc_node, ma_ns.yCoordinate, Literal(y, datatype=XSD.integer)))
    return loc_node

def create_time_instant(g, ma_ns, time_ns, time_val):
    instant_uri = URIRef(f"http://example.org/ma#time_instant_{time_val}")
    g.add((instant_uri, RDF.type, time_ns.Instant))
    g.add((instant_uri, time_ns.inXSDDateTimeStamp, Literal(f"1970-01-01T00:00:{time_val:02}Z", datatype=XSD.dateTimeStamp)))
    return instant_uri

def create_time_interval(g, ma_ns, time_ns, start_time, end_time):
    interval_node = BNode()
    start_instant = create_time_instant(g, ma_ns, time_ns, start_time)
    end_instant = create_time_instant(g, ma_ns, time_ns, end_time)
    g.add((interval_node, RDF.type, time_ns.Interval))
    g.add((interval_node, time_ns.hasBeginning, start_instant))
    g.add((interval_node, time_ns.hasEnd, end_instant))
    return interval_node

def integrate(json_path, base_ttl, out_ttl):
    try:
        with open(json_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: JSON log file not found at '{json_path}'")
        return
    except json.JSONDecodeError:
        print(f"Error: Could not parse JSON file '{json_path}'")
        return

    g = Graph()
    g.parse(base_ttl, format='turtle')

    MA = Namespace('http://example.org/ma#')
    SOSA = Namespace('http://www.w3.org/ns/sosa/')
    TIME = Namespace('http://www.w3.org/2006/time#')
    PROV = Namespace('http://www.w3.org/ns/prov#')
    g.bind('ma', MA)
    g.bind('sosa', SOSA)
    g.bind('time', TIME)
    g.bind('prov', PROV)

    # --- Environment ---
    if 'environment' in data:
        env_data = data['environment']
        env = URIRef(MA + env_data['id'])
        g.add((env, RDF.type, MA.Environment))
        if 'gridSize' in env_data:
            w, h = env_data['gridSize']
            g.add((env, MA.hasGridWidth, Literal(w, datatype=XSD.integer)))
            g.add((env, MA.hasGridHeight, Literal(h, datatype=XSD.integer)))
        for obs in env_data.get('obstacles', []):
            node = URIRef(MA + obs['id'])
            g.add((node, RDF.type, MA.Obstacle))
            loc_node = create_grid_location(g, MA, obs['cell'][0], obs['cell'][1])
            g.add((node, MA.atLocation, loc_node))
            g.add((env, MA.hasObstacle, node))

    # --- Agents ---
    for ag in data.get('agents', []):
        a = URIRef(MA + ag['id'])
        g.add((a, RDF.type, MA.Agent))
        g.add((a, RDF.type, SOSA.Platform))
        if 'initialState' in ag:
            loc_node = create_grid_location(g, MA, ag['initialState']['cell'][0], ag['initialState']['cell'][1])
            g.add((a, MA.hasInitialLocation, loc_node))
        if 'goalState' in ag:
            loc_node = create_grid_location(g, MA, ag['goalState']['cell'][0], ag['goalState']['cell'][1])
            g.add((a, MA.hasGoalLocation, loc_node))

    # --- Original Agent SubPlans ---
    for path in data.get('agentPaths', []):
        sp = URIRef(MA + path['subplanId'])
        g.add((sp, RDF.type, MA.OriginalSubPlan))
        g.add((sp, MA.belongsToAgent, URIRef(MA + path['agent'])))
        g.add((sp, MA.hasPlanCost, Literal(path['planCost'], datatype=XSD.decimal)))
        for i, step in enumerate(path.get('steps', [])):
            seg_uri = URIRef(MA + f"{path['subplanId']}_seg{i}")
            g.add((seg_uri, RDF.type, MA.AgentPathSegment))
            g.add((sp, MA.planData, seg_uri))
            interval_node = create_time_interval(g, MA, TIME, step['time'], step['time'] + 1)
            g.add((seg_uri, MA.hasValidTime, interval_node))
            path_list = BNode()
            loc_node = create_grid_location(g, MA, step['cell'][0], step['cell'][1])
            g.add((seg_uri, MA.hasPathSequence, path_list))
            g.add((path_list, RDF.first, loc_node))
            g.add((path_list, RDF.rest, RDF.nil))

    # --- Resolved Agent Subplans with Provenance ---
    for plan in data.get('agentSubplans', []):
        sp = URIRef(MA + plan['id'])
        g.add((sp, RDF.type, MA.ResolvedSubPlan))
        g.add((sp, MA.belongsToAgent, URIRef(MA + plan['belongsToAgent'])))
        g.add((sp, MA.hasPlanCost, Literal(plan['planCost'], datatype=XSD.decimal)))
        agent_uri = URIRef(MA + plan['belongsToAgent'])
        q_orig_plan = "SELECT ?plan WHERE { ?plan a ma:OriginalSubPlan ; ma:belongsToAgent ?agent . }"
        orig_plan_results = g.query(q_orig_plan, initBindings={'agent': agent_uri})
        if orig_plan_results:
            orig_plan_uri = list(orig_plan_results)[0][0]
            g.add((sp, MA.derivesFrom, orig_plan_uri))
        if 'generatedBy' in plan:
            activity_uri = URIRef(MA + plan['id'] + "_activity")
            g.add((activity_uri, RDF.type, PROV.Activity))
            g.add((sp, MA.generatedBy, activity_uri))
            g.add((activity_uri, PROV.used, URIRef(MA + plan['generatedBy'])))
        if 'derivedFromConflict' in plan:
            g.add((sp, MA.resolvesConflict, URIRef(MA + plan['derivedFromConflict'])))
        for i, step in enumerate(plan.get('steps', [])):
            seg_uri = URIRef(MA + f"{plan['id']}_seg{i}")
            g.add((seg_uri, RDF.type, MA.AgentPathSegment))
            g.add((sp, MA.planData, seg_uri))
            interval_node = create_time_interval(g, MA, TIME, step['time'], step['time'] + 1)
            g.add((seg_uri, MA.hasValidTime, interval_node))
            path_list = BNode()
            loc_node = create_grid_location(g, MA, step['cell'][0], step['cell'][1])
            g.add((seg_uri, MA.hasPathSequence, path_list))
            g.add((path_list, RDF.first, loc_node))
            g.add((path_list, RDF.rest, RDF.nil))

    # --- Collision Events ---
    for ev in data.get('collisionEvents', []):
        node = URIRef(MA + ev['id'])
        g.add((node, RDF.type, MA.CollisionEvent))
        g.add((node, MA.conflictTypeEvent, Literal(ev['type'])))
        instant_node = create_time_instant(g, MA, TIME, ev['time'])
        g.add((node, MA.occursAtTime, instant_node))

        # FIX: Correctly process locations for both edge and vertex conflicts.
        # This now handles multiple locations for edge conflicts if they are provided in the input JSON.
        locations = ev['location']
        # Ensure locations are in a list format to handle both vertex (single item) and edge (list of items).
        if not isinstance(locations, list) or not all(isinstance(loc, list) for loc in locations):
             # Wrap a single location (vertex) in a list to use a single loop
             locations = [locations]

        for loc_data in locations:
            # Ensure loc_data is a list with 2 elements before creating a location
            if isinstance(loc_data, list) and len(loc_data) == 2:
                loc_node = create_grid_location(g, MA, loc_data[0], loc_data[1])
                g.add((node, MA.conflictLocation, loc_node))

        for agent_id in ev['agents']:
            g.add((node, MA.involvesAgentsEvent, URIRef(MA + agent_id)))

    # --- Other sections ---
    for strategy in data.get('replanningStrategies', []):
        strat_node = URIRef(MA + strategy['id'])
        g.add((strat_node, RDF.type, MA.ReplanningStrategy))
        if 'triggeredBy' in strategy:
            g.add((strat_node, MA.triggeredBy, URIRef(MA + strategy['triggeredBy'])))

    for alert in data.get('conflictAlerts', []):
        aNode = URIRef(MA + alert['id'])
        g.add((aNode, RDF.type, MA.ConflictAlert))
        g.add((aNode, MA.alertsConflict, URIRef(MA + alert['alertsConflict'])))
        g.add((aNode, MA.targetAgent, URIRef(MA + alert['targetAgent'])))
        if 'rationale' in alert:
            g.add((aNode, MA.selectionRationale, Literal(alert['rationale'])))

    if 'jointPlan' in data:
        jp_data = data['jointPlan']
        jp = URIRef(MA + jp_data['id'])
        g.add((jp, RDF.type, MA.JointPlan))
        g.add((jp, MA.hasGlobalMakespan, Literal(jp_data['globalMakespan'], datatype=XSD.decimal)))
        for sp_id in jp_data['subplans']:
            g.add((jp, MA.composedOfSubPlans, URIRef(MA + sp_id)))

    try:
        g.serialize(destination=out_ttl, format='turtle')
        print(f"Knowledge graph successfully generated at '{out_ttl}'")
    except Exception as e:
        print(f"Error serializing graph to '{out_ttl}': {e}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generate knowledge graph from MAPF JSON logs into ontology instance TTL")
    parser.add_argument("--log_file", help="Path to the JSON log file")
    parser.add_argument("--ontology", default="./ontology/ma-ontology.ttl", help="Path to the ontology TTL file")
    parser.add_argument("--output", default="mapf_instance.ttl", help="Output TTL file path")
    args = parser.parse_args()

    integrate(args.log_file, args.ontology, args.output)