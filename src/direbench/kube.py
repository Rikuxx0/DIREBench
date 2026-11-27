"""Kubernetes CLI boundary, restricted to the dedicated local experiment context."""
import json
import subprocess
import time

CONTEXT = "k3d-direbench"
NAMESPACE = "direbench"


class KubeError(RuntimeError):
    pass


def command(args, *, namespace=True, input_text=None, timeout=60, check=True):
    prefix = ["kubectl", "--context", CONTEXT]
    if namespace:
        prefix += ["--namespace", NAMESPACE]
    proc = subprocess.run(prefix + list(args), input=input_text, text=True, capture_output=True, timeout=timeout)
    if check and proc.returncode:
        raise KubeError(f"{' '.join(prefix + list(args))}: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def verify_context():
    proc = subprocess.run(["kubectl", "config", "get-contexts", "-o", "name"], text=True, capture_output=True)
    if proc.returncode or CONTEXT not in proc.stdout.splitlines():
        raise KubeError(f"Dedicated context {CONTEXT} is unavailable")
    command(["cluster-info"], namespace=False, timeout=10)


def get(kind, name=None):
    args = ["get", kind]
    if name:
        args.append(name)
    args += ["-o", "json"]
    return json.loads(command(args).stdout)


def apply(obj):
    import yaml
    command(["apply", "-f", "-"], input_text=yaml.safe_dump_all(obj if isinstance(obj, list) else [obj], sort_keys=False))


def delete(kind, name, *, ignore=True):
    command(["delete", kind, name, "--ignore-not-found=" + str(ignore).lower(), "--wait=true"], timeout=90)


def reset_namespace():
    verify_context()
    command(["delete", "namespace", NAMESPACE, "--ignore-not-found=true", "--wait=true"], namespace=False, timeout=120)
    command(["create", "namespace", NAMESPACE], namespace=False)
    # A fresh namespace cannot inherit RoleBindings or NetworkPolicies from a prior trial.
    for kind in ("rolebindings", "networkpolicies", "pods"):
        if get(kind).get("items"):
            raise KubeError(f"Residual {kind} after namespace reset")


def down_namespace():
    """Remove only the benchmark namespace; keep the dedicated cluster and local results."""
    verify_context()
    command(["delete", "namespace", NAMESPACE, "--ignore-not-found=true", "--wait=true"], namespace=False, timeout=120)


def ready(deployment, timeout=120):
    command(["rollout", "status", f"deployment/{deployment}", f"--timeout={timeout}s"], timeout=timeout + 10)


def scale(deployment, replicas):
    command(["scale", "deployment", deployment, f"--replicas={replicas}"])
    if replicas:
        ready(deployment)
    else:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            items = get("pods").get("items", [])
            if not any(p["metadata"].get("labels", {}).get("component") == deployment for p in items):
                return
            time.sleep(1)
        raise KubeError(f"Timed out scaling {deployment} to zero")


def pod_ip(component):
    for pod in get("pods").get("items", []):
        if pod["metadata"].get("labels", {}).get("component") == component and pod.get("status", {}).get("phase") == "Running":
            return pod["status"].get("podIP")
    return None


def pod_name(component):
    for pod in get("pods").get("items", []):
        if pod["metadata"].get("labels", {}).get("component") == component and pod.get("status", {}).get("phase") == "Running":
            return pod["metadata"]["name"]
    raise KubeError(f"No running pod for {component}")
