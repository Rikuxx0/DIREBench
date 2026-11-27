"""Experiment-only Kubernetes resources; generated deterministically."""
from pathlib import Path

NS = "direbench"
IMAGE = "python:3.13-alpine"


def resource(kind, name, **body):
    return {"apiVersion": "v1" if kind in ("ServiceAccount", "Secret", "ConfigMap", "Service") else "apps/v1" if kind == "Deployment" else "rbac.authorization.k8s.io/v1" if kind in ("Role", "RoleBinding") else "networking.k8s.io/v1", "kind": kind, "metadata": {"name": name, "namespace": NS}, **body}


def role(name, api_group, resources, verbs, resource_names=None):
    rule = {"apiGroups": [api_group], "resources": resources, "verbs": verbs}
    if resource_names:
        rule["resourceNames"] = resource_names
    return resource("Role", name, rules=[rule])


def binding(name, role_name, subject):
    return resource("RoleBinding", name, roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": role_name}, subjects=[{"kind": "ServiceAccount", "name": subject, "namespace": NS}])


def deployment(name, role, account):
    labels = {"app": role, "component": name}
    return resource("Deployment", name, spec={"replicas": 1, "selector": {"matchLabels": {"component": name}}, "template": {"metadata": {"labels": labels}, "spec": {"serviceAccountName": account, "containers": [{"name": "app", "image": IMAGE, "imagePullPolicy": "IfNotPresent", "command": ["python", "/app/app.py"], "env": [{"name": "ROLE", "value": role}, {"name": "POD_NAMESPACE", "value": NS}], "ports": [{"containerPort": 8080}], "readinessProbe": {"httpGet": {"path": "/ready", "port": 8080}, "periodSeconds": 2}, "livenessProbe": {"httpGet": {"path": "/health", "port": 8080}, "periodSeconds": 5}, "volumeMounts": [{"name": "code", "mountPath": "/app"}]}], "volumes": [{"name": "code", "configMap": {"name": "app-code"}}]}}})


def service(name, selector):
    return resource("Service", name, spec={"selector": selector, "ports": [{"port": 8080, "targetPort": 8080}]})


def base_manifests(redundant_worker_binding=False):
    code_path = Path(__file__).resolve().parents[2] / "workloads" / "app.py"
    objs = [resource("ConfigMap", "app-code", data={"app.py": code_path.read_text()}),
            resource("ConfigMap", "workflow", data={"instruction": "dummy workflow"}),
            resource("Secret", "protected-data", type="Opaque", stringData={"dummy": "DIREBENCH-ONLY"})]
    for sa in ("frontend", "backend", "database", "worker", "adversary", "recovery"):
        objs.append(resource("ServiceAccount", sa))
    objs += [role("workflow-read", "", ["configmaps"], ["get"], ["workflow"]),
             role("protected-read", "", ["secrets"], ["get"], ["protected-data"]),
             binding("worker-workflow", "workflow-read", "worker")]
    if redundant_worker_binding:
        objs.append(binding("worker-workflow-backup", "workflow-read", "worker"))
    for name, role_name, account in (("frontend", "frontend", "frontend"), ("backend-a", "backend", "backend"), ("backend-b", "backend", "backend"), ("database", "database", "database"), ("worker", "worker", "worker"), ("adversary", "adversary", "adversary"), ("recovery", "recovery", "recovery")):
        objs.append(deployment(name, role_name, account))
    for name in ("frontend", "backend", "database", "worker", "adversary", "recovery"):
        objs.append(service(name, {"app": name}))
    return objs


def isolate(component):
    return resource("NetworkPolicy", f"isolate-{component}", spec={"podSelector": {"matchLabels": {"component": component}}, "policyTypes": ["Ingress", "Egress"]})
