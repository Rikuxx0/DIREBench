"""Structured defense operators and guarded real Kubernetes mutations."""
from datetime import datetime, timezone

from . import kube, manifests


def definition(name):
    if name.startswith("isolate-"):
        target = name.removeprefix("isolate-")
        if target not in ("backend-a", "backend-b", "adversary"):
            raise ValueError(name)
        return {"operator_id": name, "action_type": "isolate", "target": target, "actor": "defense-agent", "parameters": {"drain_service_endpoint": target.startswith("backend-")}, "preconditions": ["target pod is running"], "expected_effects": ["target ingress and egress denied"], "affected_resources": [f"pod/{target}", f"networkpolicy/isolate-{target}"], "authorization_requirements": ["dedicated context", "experiment namespace"], "reversible": True, "rollback_operation": f"release-{target}", "observation_requirements": ["pod labels", "service endpoints", "target reachability"]}
    if name.startswith("release-"):
        target = name.removeprefix("release-")
        if target not in ("backend-a", "backend-b", "adversary"):
            raise ValueError(name)
        return {"operator_id": name, "action_type": "release", "target": target, "actor": "defense-agent", "parameters": {}, "preconditions": [], "expected_effects": ["restore original routing"], "affected_resources": [f"pod/{target}"], "authorization_requirements": ["dedicated context"], "reversible": True, "rollback_operation": f"isolate-{target}", "observation_requirements": ["pod labels"]}
    if name == "remove-worker-binding":
        return {"operator_id": name, "action_type": "remove_binding", "target": "worker-workflow", "actor": "defense-agent", "parameters": {}, "preconditions": [], "expected_effects": ["remove one RoleBinding"], "affected_resources": ["rolebinding/worker-workflow"], "authorization_requirements": ["dedicated context"], "reversible": True, "rollback_operation": "restore-worker-binding", "observation_requirements": ["rolebindings"]}
    if name in ("grant-adversary-secret", "grant-recovery-workflow"):
        return {"operator_id": name, "action_type": "grant", "target": "adversary" if name == "grant-adversary-secret" else "recovery", "actor": "defense-agent", "parameters": {"role": "protected-read" if name == "grant-adversary-secret" else "workflow-read"}, "preconditions": [], "expected_effects": ["new role binding"], "affected_resources": ["rolebindings"], "authorization_requirements": ["dedicated context"], "reversible": True, "rollback_operation": "delete grant binding", "observation_requirements": ["rolebindings", "serviceaccounts"]}
    raise ValueError(name)


def execute(name):
    op = definition(name)
    target = op["target"]
    steps = []
    def record(step):
        steps.append({"time": datetime.now(timezone.utc).isoformat(), "step": step})
    if op["action_type"] == "isolate":
        if op["parameters"]["drain_service_endpoint"]:
            kube.command(["label", "pod", kube.pod_name(target), "app=isolated", "--overwrite"])
            record("drain_service_endpoint")
        kube.apply(manifests.isolate(target))
        record("apply_network_policy")
    elif op["action_type"] == "release":
        kube.delete("networkpolicy", f"isolate-{target}")
        record("delete_network_policy")
        if target.startswith("backend-"):
            kube.command(["label", "pod", kube.pod_name(target), "app=backend", "--overwrite"])
            record("restore_service_endpoint")
    elif op["action_type"] == "remove_binding":
        kube.delete("rolebinding", target, ignore=False)
        record("delete_role_binding")
    elif op["action_type"] == "grant":
        role = op["parameters"]["role"]
        kube.apply(manifests.binding(f"grant-{target}-{role}", role, target))
        record("apply_role_binding")
    return {"operation": op, "steps": steps}
