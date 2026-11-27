import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from direbench import cli, kube, measure, metrics, supervisor


def state(backends=2, worker_bindings=1):
    pods = [{"labels": {"component": f"backend-{x}", "app": "backend"}, "ready": True, "phase": "Running"} for x in "ab"[:backends]]
    return {"timestamp": measure.now(), "state_version": {"pods": "1"}, "resources": {"pods": pods, "rolebindings": [{"name": f"worker-workflow-{i}"} for i in range(worker_bindings)]}}


class Boundaries(unittest.TestCase):
    def test_kubectl_always_passes_dedicated_context_and_namespace(self):
        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            kube.command(["get", "pods"])
            args = run.call_args.args[0]
            self.assertEqual(args[:4], ["kubectl", "--context", "k3d-direbench", "--namespace"])
            self.assertEqual(args[4], "direbench")

    def test_down_removes_only_benchmark_namespace(self):
        with patch("direbench.kube.verify_context") as verify, patch("direbench.kube.command") as command:
            kube.down_namespace()
            verify.assert_called_once_with()
            command.assert_called_once_with(["delete", "namespace", "direbench", "--ignore-not-found=true", "--wait=true"], namespace=False, timeout=120)

    def test_b2_detects_last_endpoint_but_not_redundant_endpoint(self):
        one = supervisor.decide("B2", "isolate-backend-a", state(1))
        two = supervisor.decide("B2", "isolate-backend-a", state(2))
        self.assertEqual(one["decision"], "DENY")
        self.assertEqual(two["decision"], "ALLOW")

    def test_b3_reobserves_on_version_change_even_with_fresh_timestamp(self):
        old = state(2)
        current = state(2)
        current["state_version"]["pods"] = "changed"
        decision = supervisor.decide("B3", "isolate-backend-a", old, fresh_observed=current)
        self.assertEqual(decision["decision"], "REOBSERVE")

    def test_ground_truth_uses_probe_delta_independent_of_prediction(self):
        def reading(status):
            return {"traffic": {"frontend": [{"status": status}], "worker": [{"status": status}]}, "secret_access": {"adversary": {"status": 200, "body": {"access": False}}}}
        truth = measure.summarize(reading(200), reading(503), scenario="test")
        self.assertTrue(truth["risk_observed"])
        self.assertTrue(truth["availability_loss"])

    def test_rejected_action_requires_separate_b0_control_for_detection_metric(self):
        rows = [({"baseline": "B2", "scenario": "case", "seed": 1, "status": "completed"}, {"risk_observed": False}, [{"executed": False}])]
        self.assertEqual(metrics.paired_detection(rows), {})
        rows.append(({"baseline": "B0", "scenario": "case", "seed": 1, "status": "completed"}, {"risk_observed": True}, [{"executed": True}]))
        self.assertEqual(metrics.paired_detection(rows)["B2"]["TP"], 1)

    def test_run_is_one_case_and_reproduce_is_category_b0(self):
        with patch("direbench.cli.runner.run_trial", return_value=(Path("trial"), {"status": "completed"})) as trial, redirect_stdout(StringIO()):
            self.assertEqual(cli.main(["run", "--scenario", "S1-single", "--baseline", "B2"]), 0)
            self.assertEqual(trial.call_count, 1)
            self.assertEqual(trial.call_args.args[1], "B2")
            trial.reset_mock()
            self.assertEqual(cli.main(["reproduce", "--scenario", "S1"]), 0)
            self.assertEqual(trial.call_count, 3)
            self.assertTrue(all(call.args[1] == "B0" for call in trial.call_args_list))

    def test_all_runs_full_matrix_and_ablations_without_setup(self):
        with patch("direbench.cli.runner.run_trial", return_value=(Path("trial"), {"status": "completed"})) as trial, patch("direbench.cli.report", return_value=0) as report, patch("direbench.cli.preflight") as preflight, redirect_stdout(StringIO()):
            self.assertEqual(cli.main(["all", "--traffic-samples", "2"]), 0)
            self.assertEqual(trial.call_count, 81)
            self.assertEqual(report.call_count, 1)
            preflight.assert_not_called()
            self.assertEqual([call.args[1] for call in trial.call_args_list[:5]], ["B0", "B1", "B2", "B3", "ALL_DENY"])
            self.assertTrue(all(call.kwargs["traffic_samples"] == 2 for call in trial.call_args_list))


if __name__ == "__main__":
    unittest.main()
