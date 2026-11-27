"""Trial orchestration and append-only evidence artifact writing."""
import csv
import hashlib
import json
import platform
import random
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from . import graphs, kube, manifests, measure, operators, supervisor

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results"


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def write_jsonl(path, items):
    path.write_text("".join(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n" for item in items))


def version(command):
    try:
        return subprocess.run(command, text=True, capture_output=True, timeout=10).stdout.strip()
    except Exception as exc:
        return str(exc)


def source_digest():
    digest = hashlib.sha256()
    for path in sorted((ROOT / "src" / "direbench").glob("*.py")) + [ROOT / "workloads" / "app.py"]:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


PROCESS_SOURCE_SHA256 = source_digest()


def deploy(*, redundant=False):
    kube.reset_namespace()
    kube.apply(manifests.base_manifests(redundant))
    for name in ("frontend", "backend-a", "backend-b", "database", "worker", "adversary", "recovery"):
        kube.ready(name)


def network_policy_preflight():
    deploy()
    ip = kube.pod_ip("adversary")
    before = measure.probe_url("worker", f"http://{ip}:8080/health")
    kube.apply(manifests.isolate("adversary"))
    measure.settle()
    after = measure.probe_url("worker", f"http://{ip}:8080/health")
    kube.delete("networkpolicy", "isolate-adversary")
    measure.settle()
    restored = measure.probe_url("worker", f"http://{ip}:8080/health")
    ok = before.get("status") == 200 and after.get("status") != 200 and restored.get("status") == 200
    return {"network_policy_enforced": ok, "before": before, "after": after, "restored": restored}


def _setup(scenario):
    if scenario.setup in ("single", "lose-b"):
        kube.scale("backend-b", 0)


def _events():
    proc = kube.command(["get", "events", "-o", "json"], check=False)
    if proc.returncode:
        return [{"error": proc.stderr.strip()}]
    return [{"reason": x.get("reason"), "message": x.get("message"), "eventTime": x.get("eventTime") or x.get("lastTimestamp"), "involvedObject": x.get("involvedObject", {})} for x in json.loads(proc.stdout).get("items", [])]


def _decision(baseline, name, observed, *, fresh=None, ablation=None):
    options = ablation or {}
    d = supervisor.decide(baseline, name, observed, fresh_observed=fresh, sequential=options.get("sequential", True), freshness=options.get("freshness", True), evidence=options.get("evidence", True))
    if d["decision"] == "REOBSERVE":
        current = fresh or measure.snapshot()
        second = supervisor.decide("B2", name, current)
        return [d, second], second["decision"] == "ALLOW"
    return [d], d["decision"] == "ALLOW"


def run_trial(scenario, baseline="B0", *, seed=7, traffic_samples=3, check_network=True, ablation=None):
    RESULTS.mkdir(exist_ok=True)
    trial_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + scenario.id + "-" + baseline + "-" + uuid.uuid4().hex[:8]
    directory = RESULTS / trial_id
    directory.mkdir()
    random.seed(seed)
    started = time.monotonic()
    metadata = {"trial_id": trial_id, "scenario": scenario.id, "baseline": baseline, "seed": seed, "traffic_samples": traffic_samples, "process_source_sha256": PROCESS_SOURCE_SHA256, "source_sha256": source_digest(), "started_utc": measure.now(), "status": "running", "platform": platform.platform(), "kubectl_version": version(["kubectl", "version", "--client"]), "cluster_version": version(["kubectl", "--context", kube.CONTEXT, "version", "-o", "json"]), "context": kube.CONTEXT, "namespace": kube.NAMESPACE, "image": manifests.IMAGE, "ablation": ablation or {}}
    write_json(directory / "experiment_metadata.json", metadata)
    write_json(directory / "scenario.json", {"id": scenario.id, "category": scenario.category, "description": scenario.description, "setup": scenario.setup, "operations": list(scenario.operations), "mode": scenario.mode})
    import yaml
    (directory / "scenario.yaml").write_text(yaml.safe_dump({"id": scenario.id, "category": scenario.category, "description": scenario.description, "setup": scenario.setup, "operations": list(scenario.operations), "mode": scenario.mode}, sort_keys=False))
    proposed, decisions, trace, predicted = [], [], [], []
    try:
        deploy(redundant=scenario.setup == "redundant")
        observed = measure.snapshot() if scenario.observe_before_setup else None
        _setup(scenario)
        measure.settle(2)
        initial_state = measure.snapshot()
        if observed is None:
            observed = initial_state
        write_json(directory / "initial_state.json", initial_state)
        write_json(directory / "observed_state.json", observed)
        before = measure.measure(traffic_samples)
        write_json(directory / "graph_before.json", {"attack": graphs.attack_graph(initial_state, before), "service_dependency": graphs.dependency_graph(before)})
        (directory / "graph_before.dot").write_text(graphs.to_dot(graphs.attack_graph(initial_state, before)))
        if check_network and any(x.startswith("isolate-") for x in scenario.operations):
            # Confirm actual CNI enforcement on a separate pod in this freshly reset trial.
            ip = kube.pod_ip("adversary")
            if not ip:
                raise RuntimeError("NetworkPolicy target unavailable")
            np_before = measure.probe_url("worker", f"http://{ip}:8080/health")
            kube.apply(manifests.isolate("adversary"))
            measure.settle()
            np_after = measure.probe_url("worker", f"http://{ip}:8080/health")
            kube.delete("networkpolicy", "isolate-adversary")
            measure.settle()
            np_restored = measure.probe_url("worker", f"http://{ip}:8080/health")
            write_json(directory / "network_policy_preflight.json", {"before": np_before, "after": np_after, "restored": np_restored})
            if np_before.get("status") != 200 or np_after.get("status") == 200 or np_restored.get("status") != 200:
                raise RuntimeError("NetworkPolicy enforcement not demonstrated; trial invalid")
        current_observed = observed
        if scenario.mode == "parallel":
            plans = []
            reserved = deepcopy(current_observed)
            reserved_targets = []
            for name in scenario.operations:
                proposed.append(operators.definition(name))
                basis = reserved if baseline == "B3" and (ablation or {}).get("sequential", True) else current_observed
                fresh = measure.snapshot() if baseline == "B3" else None
                if fresh is not None and basis is reserved:
                    # Reobservation must retain operations already approved in the same parallel batch.
                    for pod in fresh["resources"]["pods"]:
                        if pod["labels"].get("component") in reserved_targets:
                            pod["labels"]["app"] = "isolated"
                ds, allowed = _decision(baseline, name, basis, fresh=fresh, ablation=ablation)
                decisions.extend(ds)
                predicted.extend(ds)
                plans.append((name, allowed))
                if allowed and basis is reserved:
                    reserved_targets.append(operators.definition(name)["target"])
                    for pod in reserved["resources"]["pods"]:
                        if pod["labels"].get("component") == operators.definition(name)["target"]:
                            pod["labels"]["app"] = "isolated"
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {name: pool.submit(operators.execute, name) for name, allowed in plans if allowed}
                for name, allowed in plans:
                    result = futures[name].result() if allowed and futures[name].exception() is None else None
                    trace.append({"time": measure.now(), "operation": name, "executed": allowed, "result": "applied" if allowed and result else "error" if allowed else "withheld", "steps": result["steps"] if result else [], "error": str(futures[name].exception()) if allowed and futures[name].exception() else None})
        else:
            for name in scenario.operations:
                proposed.append(operators.definition(name))
                fresh = measure.snapshot() if baseline == "B3" else None
                ds, allowed = _decision(baseline, name, current_observed, fresh=fresh, ablation=ablation)
                decisions.extend(ds)
                predicted.extend(ds)
                result = None
                if allowed:
                    result = operators.execute(name)
                    measure.settle()
                trace.append({"time": measure.now(), "operation": name, "executed": allowed, "result": "applied" if allowed else "withheld", "steps": result["steps"] if result else []})
                current_observed = measure.snapshot()  # B2 sees the effect of the preceding operation.
        measure.settle()
        after = measure.measure(traffic_samples)
        measured_state = measure.snapshot()
        measured_state["operation_history"] = trace
        measured_state["network_reachability"] = after["adversary_backend_access"]
        measured_state["live_permission_probes"] = after["secret_access"]
        truth = measure.summarize(before, after, scenario=scenario.id)
        write_json(directory / "measured_state.json", measured_state)
        write_json(directory / "ground_truth.json", {"before": before, "after": after, "outcome": truth})
        write_json(directory / "graph_after.json", {"attack": graphs.attack_graph(measured_state, after), "service_dependency": graphs.dependency_graph(after)})
        (directory / "graph_after.dot").write_text(graphs.to_dot(graphs.attack_graph(measured_state, after)))
        write_jsonl(directory / "access_probe_results.jsonl", [{"phase": "before", "data": before}, {"phase": "after", "data": after}])
        write_jsonl(directory / "kubernetes_events.jsonl", _events())
        decision_evidence = []
        for item in decisions:
            decision_evidence.append({"proposed_operation": item["proposed_operation"], "observed_state_version": item["observed_state_version"], "observation_timestamp": item["observation_timestamp"], "graph_before": "graph_before.json", "predicted_graph_after": item["predicted_graph_after"], "affected_dependencies": item["affected_dependencies"], "predicted_permission_delta": item["predicted_permission_delta"], "predicted_reachability_delta": item["predicted_reachability_delta"], "violated_constraints": item["violated_constraints"], "uncertainty": item["uncertainty"], "decision": item["decision"], "decision_reason": item["decision_reason"], "measured_state_after": "measured_state.json", "prediction_errors": None, "prediction_error_status": "not_causally_attributable_from_final_state_alone", "evidence_references": ["observed_state.json", "graph_before.json", "graph_after.json", "execution_trace.jsonl", "ground_truth.json"]})
        if (ablation or {}).get("evidence", True):
            write_jsonl(directory / "decision_evidence.jsonl", decision_evidence)
        with (directory / "service_metrics.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["phase", "component", "time", "status"])
            writer.writeheader()
            for phase, data in (("before", before), ("after", after)):
                for component, samples in data["traffic"].items():
                    for x in samples:
                        writer.writerow({"phase": phase, "component": component, "time": x["time"], "status": x["status"]})
        evaluation = {"risk_observed": truth["risk_observed"], "measurement_valid": truth["measurement_valid"], "any_operation_executed": any(x["executed"] for x in trace), "rejected_operations": sum(not x["executed"] for x in trace), "trial_elapsed_seconds": time.monotonic() - started}
        write_json(directory / "evaluation.json", evaluation)
        if (ablation or {}).get("evidence", True):
            (directory / "explanation.md").write_text("# 検証可能な判断\n\n" + "\n".join(f"- {d['proposed_operation']['operator_id']}: {d['decision']} — {d['decision_reason']} (観測: {d['observation_timestamp']})" for d in decisions) + "\n\n実測結果は `ground_truth.json` を参照。拒否操作の反実仮想は独立した B0 試行で評価する。\n")
        metadata["status"] = "completed" if truth["measurement_valid"] else "measurement_failed"
    except Exception as exc:
        metadata["status"] = "experiment_failed"
        metadata["error"] = str(exc)
    finally:
        write_jsonl(directory / "proposed_operations.jsonl", proposed)
        write_jsonl(directory / "supervisor_decisions.jsonl", decisions)
        write_jsonl(directory / "predicted_states.jsonl", predicted)
        write_jsonl(directory / "execution_trace.jsonl", trace)
        metadata["finished_utc"] = measure.now()
        metadata["source_sha256_finished"] = source_digest()
        if metadata["status"] == "completed" and len({metadata["process_source_sha256"], metadata["source_sha256"], metadata["source_sha256_finished"]}) != 1:
            metadata["status"] = "provenance_invalid"
            metadata["error"] = "Source files changed during the process or trial"
        write_json(directory / "experiment_metadata.json", metadata)
    return directory, metadata
