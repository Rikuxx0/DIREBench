"""Configuration-derived graph with separately recorded probe evidence."""
import json


def attack_graph(state, measured=None):
    nodes, edges = [], []
    resources = state["resources"]
    for kind, items in resources.items():
        for item in items:
            nodes.append({"id": f"{kind}/{item['name']}", "type": kind})
    for pod in resources["pods"]:
        edges.append({"from": f"pods/{pod['name']}", "to": f"serviceaccounts/{pod['serviceAccountName']}", "type": "runs_as", "source": "kubernetes_api"})
    for binding in resources["rolebindings"]:
        ref = binding.get("roleRef") or {}
        for subject in binding.get("subjects", []):
            if subject.get("kind") == "ServiceAccount":
                edges.append({"from": f"serviceaccounts/{subject['name']}", "to": f"roles/{ref.get('name')}", "type": "binds_to", "source": "kubernetes_api"})
    for role in resources["roles"]:
        for rule in role.get("rules", []):
            for kind in rule.get("resources", []):
                for name in rule.get("resourceNames", ["*"]):
                    edges.append({"from": f"roles/{role['name']}", "to": f"{kind}/{name}", "type": "grants_permission", "verbs": rule.get("verbs", []), "source": "kubernetes_api"})
    if measured:
        for principal, result in measured["secret_access"].items():
            if result.get("status") == 200:
                edges.append({"from": f"serviceaccounts/{principal}", "to": "secrets/protected-data", "type": "can_read", "observed": result.get("body", {}).get("access"), "source": "live_access_probe"})
        for target, result in measured["adversary_backend_access"].items():
            if result.get("status") == 200:
                edges.append({"from": "pods/adversary", "to": f"pods/{target}", "type": "can_connect", "observed": result.get("body", {}).get("access"), "source": "live_http_probe"})
    return {"nodes": nodes, "edges": edges}


def dependency_graph(measured=None):
    edges = [{"from": "frontend", "to": "backend", "type": "required", "minimum_healthy": 1, "source": "application_code"},
             {"from": "worker", "to": "backend", "type": "required", "minimum_healthy": 1, "source": "application_code"},
             {"from": "worker", "to": "configmaps/workflow", "type": "required", "minimum_healthy": 1, "source": "application_code"},
             {"from": "backend", "to": "database", "type": "required", "minimum_healthy": 1, "source": "application_code"},
             {"from": "backend", "to": "backend-a|backend-b", "type": "alternative", "minimum_healthy": 1, "source": "service_selector"}]
    result = {"edges": edges}
    if measured:
        result["observed_transactions"] = {name: [x.get("status") for x in samples] for name, samples in measured["traffic"].items()}
    return result


def to_dot(graph):
    lines = ["digraph DIREBench {"]
    for node in graph.get("nodes", []):
        lines.append(f"  {json.dumps(node['id'])} [label={json.dumps(node['id'])}];")
    for edge in graph.get("edges", []):
        label = edge["type"] + "/" + edge.get("source", "unknown")
        if "observed" in edge:
            label += "/" + str(edge["observed"]).lower()
        lines.append(f"  {json.dumps(edge['from'])} -> {json.dumps(edge['to'])} [label={json.dumps(label)}];")
    return "\n".join(lines + ["}", ""])
