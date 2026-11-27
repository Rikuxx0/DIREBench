"""Ground truth inputs from live workloads and Kubernetes API; no supervisor imports."""
import json
import time
from datetime import datetime, timezone

from . import kube

PROBE_CODE = "import json,sys,urllib.request,urllib.error;url=sys.argv[1];method=sys.argv[2];r=urllib.request.Request(url,method=method);\ntry:\n x=urllib.request.urlopen(r,timeout=4);print(json.dumps({'status':x.status,'body':json.loads(x.read())}))\nexcept urllib.error.HTTPError as e: print(json.dumps({'status':e.code,'error':e.read().decode()[:200]}))\nexcept Exception as e: print(json.dumps({'status':0,'error':str(e)}))"


def probe_url(component, url, method="GET"):
    try:
        pod = kube.pod_name(component)
        proc = kube.command(["exec", pod, "--", "python", "-c", PROBE_CODE, url, method], timeout=20, check=False)
        if proc.returncode:
            return {"status": 0, "error": proc.stderr.strip(), "time": now()}
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        result["time"] = now()
        return result
    except Exception as exc:
        return {"status": 0, "error": str(exc), "time": now()}


def probe(component, path, method="GET"):
    return probe_url(component, f"http://127.0.0.1:8080{path}", method)


def now():
    return datetime.now(timezone.utc).isoformat()


def snapshot():
    kinds = ["pods", "deployments", "services", "serviceaccounts", "roles", "rolebindings", "networkpolicies", "secrets", "configmaps"]
    raw = {kind: kube.get(kind) for kind in kinds}
    # Secret data, Pod token-related fields and unrelated managed fields are never written to results.
    stamp = now()
    state = {"state_kind": "observed", "timestamp": stamp, "observation_timestamps": {"kubernetes_api": stamp}, "resources": {}, "state_version": {}}
    for kind, listing in raw.items():
        items = []
        for item in listing.get("items", []):
            meta = item.get("metadata", {})
            entry = {"name": meta.get("name"), "labels": meta.get("labels", {}), "resourceVersion": meta.get("resourceVersion"), "kind": item.get("kind")}
            if kind == "pods":
                entry.update({"phase": item.get("status", {}).get("phase"), "podIP": item.get("status", {}).get("podIP"), "serviceAccountName": item.get("spec", {}).get("serviceAccountName"), "ready": all(c.get("ready") for c in item.get("status", {}).get("containerStatuses", []))})
            elif kind == "deployments":
                entry.update({"replicas": item.get("spec", {}).get("replicas", 0), "readyReplicas": item.get("status", {}).get("readyReplicas", 0)})
            elif kind == "services":
                entry["selector"] = item.get("spec", {}).get("selector", {})
            elif kind in ("roles", "rolebindings", "networkpolicies"):
                entry["rules" if kind == "roles" else "roleRef" if kind == "rolebindings" else "spec"] = item.get("rules" if kind == "roles" else "roleRef" if kind == "rolebindings" else "spec")
                if kind == "rolebindings":
                    entry["subjects"] = item.get("subjects", [])
            items.append(entry)
        state["resources"][kind] = items
        # kubectl may return an empty list-level resourceVersion; retain each item's API version.
        state["state_version"][kind] = {x["name"]: x["resourceVersion"] for x in items}
    state["assets"] = [f"secrets/{x['name']}" for x in state["resources"]["secrets"]] + [f"configmaps/{x['name']}" for x in state["resources"]["configmaps"]] + ["database/counter"]
    state["identities"] = [x["name"] for x in state["resources"]["serviceaccounts"]]
    state["compromised_principals"] = ["adversary"]
    state["service_health"] = {x["name"]: {"desired": x["replicas"], "ready": x["readyReplicas"]} for x in state["resources"]["deployments"]}
    state["security_constraints"] = ["adversary cannot read protected-data"]
    state["availability_constraints"] = ["frontend and worker transaction success >= 0.8"]
    state["active_permission_leases"] = []
    state["operation_history"] = []
    state["network_reachability"] = {"status": "requires_live_probe"}
    state["service_dependencies"] = {"status": "documented_in_graph_artifact"}
    roles = {x["name"]: x.get("rules", []) for x in state["resources"]["roles"]}
    permissions = {name: [] for name in state["identities"]}
    for binding in state["resources"]["rolebindings"]:
        for subject in binding.get("subjects", []):
            name = subject.get("name")
            if subject.get("kind") != "ServiceAccount" or name not in permissions:
                continue
            for rule in roles.get((binding.get("roleRef") or {}).get("name"), []):
                for verb in rule.get("verbs", []):
                    for resource in rule.get("resources", []):
                        for target in rule.get("resourceNames", ["*"]):
                            permissions[name].append({"verb": verb, "resource": resource, "target": target, "source": "kubernetes_api_inferred"})
    state["effective_permissions"] = permissions
    return state


def measure(traffic_samples=3):
    """Independent observed outcomes, including failures and sample timestamps."""
    samples = {"frontend": [], "worker": [], "recovery": []}
    for _ in range(traffic_samples):
        for component in samples:
            samples[component].append(probe(component, "/transaction", "POST"))
    backend_ips = {name: kube.pod_ip(name) for name in ("backend-a", "backend-b")}
    access = {}
    for name, ip in backend_ips.items():
        access[name] = probe("adversary", "/probe-backend?target=" + ip) if ip else {"status": 0, "body": {"access": False}, "error": "no running pod", "time": now()}
    secret = {name: probe(name, "/probe-secret") for name in ("adversary", "recovery")}
    return {"timestamp": now(), "traffic": samples, "backend_ips": backend_ips, "adversary_backend_access": access, "secret_access": secret}


def summarize(before, after, *, scenario):
    """Risk label derives only from live response deltas, never expected labels or predictions."""
    def rate(items):
        return sum(x.get("status") == 200 for x in items) / len(items) if items else None
    prior = {k: rate(v) for k, v in before["traffic"].items()}
    later = {k: rate(v) for k, v in after["traffic"].items()}
    availability_loss = any(prior[k] is not None and later[k] is not None and prior[k] - later[k] > 0.2 for k in prior)
    def access(m, principal):
        p = m["secret_access"][principal]
        return p.get("body", {}).get("access") if p.get("status") == 200 else None
    adv_before, adv_after = access(before, "adversary"), access(after, "adversary")
    confidentiality_gain = adv_before is False and adv_after is True
    missing = any(x.get("status") == 0 for m in (before, after) for group in m["traffic"].values() for x in group)
    missing |= adv_before is None or adv_after is None
    return {"scenario": scenario, "traffic_success_before": prior, "traffic_success_after": later, "availability_loss": availability_loss if not missing else None, "adversary_secret_before": adv_before, "adversary_secret_after": adv_after, "confidentiality_gain": confidentiality_gain if not missing else None, "risk_observed": (availability_loss or confidentiality_gain) if not missing else None, "measurement_valid": not missing, "classification_source": "independent_live_http_and_api_probes"}


def settle(seconds=3):
    time.sleep(seconds)
