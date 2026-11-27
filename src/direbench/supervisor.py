"""Pre-execution predictions from observed configuration only. Never reads measurements."""
from datetime import datetime, timezone

from .operators import definition


def _healthy_backend_count(observed):
    return sum(p["labels"].get("app") == "backend" and p.get("ready") and p.get("phase") == "Running" for p in observed["resources"]["pods"])


def decide(baseline, operation, observed, *, fresh_observed=None, sequential=True, freshness=True, evidence=True):
    op = definition(operation)
    decision, reason, violations = "ALLOW", "authorized_experiment_operation", []
    used = observed
    if baseline not in ("B0", "B1", "B2", "B3", "ALL_DENY"):
        raise ValueError(baseline)
    if baseline == "ALL_DENY":
        decision, reason = "DENY", "negative_control"
    elif baseline == "B3" and freshness:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(observed["timestamp"])).total_seconds()
        if age > 5 or (fresh_observed and fresh_observed["state_version"] != observed["state_version"]):
            decision, reason = "REOBSERVE", "observation_age_or_version_mismatch"
    if decision == "ALLOW" and baseline in ("B2", "B3"):
        if op["action_type"] == "isolate" and op["target"].startswith("backend-"):
            count = _healthy_backend_count(used)
            if count <= 1 and any(p["labels"].get("component") == op["target"] and p["labels"].get("app") == "backend" for p in used["resources"]["pods"]):
                decision, reason = "DENY", "predicted_loss_of_last_backend_endpoint"
                violations.append("frontend_and_worker_backend_dependency")
        elif operation == "remove-worker-binding":
            count = sum(b["name"].startswith("worker-workflow") for b in used["resources"]["rolebindings"])
            if count <= 1:
                decision, reason = "DENY", "predicted_loss_of_worker_configmap_access"
                violations.append("worker_workflow_permission")
        elif operation == "grant-adversary-secret":
            decision, reason = "DENY", "predicted_new_secret_read_for_compromised_principal"
            violations.append("protected_secret_confidentiality")
    return {"proposed_operation": op, "observed_state_version": observed["state_version"], "observation_timestamp": observed["timestamp"], "predicted_graph_after": {"backend_endpoints": max(0, _healthy_backend_count(used) - (op["action_type"] == "isolate" and op["target"].startswith("backend-")))}, "affected_dependencies": violations, "predicted_permission_delta": [op["target"]] if op["action_type"] in ("grant", "remove_binding") else [], "predicted_reachability_delta": [op["target"]] if op["action_type"] == "isolate" else [], "violated_constraints": violations, "uncertainty": [] if decision != "REOBSERVE" else ["state_changed_since_observation"], "decision": decision, "decision_reason": reason, "evidence_generated": evidence}
