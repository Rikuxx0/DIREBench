"""Exploratory causal contrasts. No outcome labels are stored here."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    description: str
    setup: str
    operations: tuple[str, ...]
    mode: str = "serial"
    observe_before_setup: bool = False


CATALOG = (
    Scenario("S1-single", "S1", "Single backend isolation", "single", ("isolate-backend-a",)),
    Scenario("S1-redundant", "S1", "Redundant backend isolation", "default", ("isolate-backend-a",)),
    Scenario("S1-independent", "S1", "Independent adversary isolation", "default", ("isolate-adversary",)),
    Scenario("S2-essential", "S2", "Remove worker's only workflow permission", "default", ("remove-worker-binding",)),
    Scenario("S2-redundant", "S2", "Remove one of two equivalent bindings", "redundant", ("remove-worker-binding",)),
    Scenario("S3-compromised", "S3", "Grant dummy protected Secret read to compromised principal", "default", ("grant-adversary-secret",)),
    Scenario("S3-recovery", "S3", "Grant workflow read to separate recovery principal", "default", ("grant-recovery-workflow",)),
    Scenario("S4-A", "S4", "Isolate backend A alone", "default", ("isolate-backend-a",)),
    Scenario("S4-B", "S4", "Isolate backend B alone", "default", ("isolate-backend-b",)),
    Scenario("S4-A-B", "S4", "A then B", "default", ("isolate-backend-a", "isolate-backend-b")),
    Scenario("S4-B-A", "S4", "B then A", "default", ("isolate-backend-b", "isolate-backend-a")),
    Scenario("S4-parallel", "S4", "A and B proposed concurrently", "default", ("isolate-backend-a", "isolate-backend-b"), "parallel"),
    Scenario("S4-rollback-B", "S4", "A, release A, then B", "default", ("isolate-backend-a", "release-backend-a", "isolate-backend-b")),
    Scenario("S5-stale", "S5", "Observe two backends, lose B, isolate A", "lose-b", ("isolate-backend-a",), observe_before_setup=True),
    Scenario("S5-fresh", "S5", "Observe two backends and isolate A", "default", ("isolate-backend-a",)),
)


def select(query):
    matches = [s for s in CATALOG if s.id == query or s.category == query]
    if not matches:
        raise ValueError(f"Unknown scenario: {query}")
    return matches
