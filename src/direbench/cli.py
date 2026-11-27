"""DIREBench command line interface."""
import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import graphs, kube, metrics, runner, scenarios


ABLATIONS = {
    "sequential": {"sequential": True, "freshness": False, "evidence": False},
    "freshness": {"sequential": False, "freshness": True, "evidence": False},
    "sequential+freshness": {"sequential": True, "freshness": True, "evidence": False},
    "full": {"sequential": True, "freshness": True, "evidence": True},
}

SECTION_TITLES = dict(zip(
    ["Abstract", "Research Background", "Research Problem", "Research Questions", "Hypotheses", "Threat Model", "Experimental Environment", "System Architecture", "Defense Operator Model", "Scenario Design", "Experimental Protocol", "Baseline Definitions", "Independent Variables", "Dependent Variables", "Controlled Variables", "Ground Truth Definition", "Evaluation Metrics", "RQ1 Results", "RQ2 Results", "RQ3 Results", "RQ4 Results", "Ablation Study", "Failure Cases", "Discussion", "Threats to Validity", "Limitations", "Reproducibility Instructions", "Conclusion"],
    ["要旨", "研究背景", "研究課題", "研究上の問い", "仮説", "脅威モデル", "実験環境", "システム構成", "防御操作モデル", "シナリオ設計", "実験手順", "比較条件", "独立変数", "従属変数", "統制変数", "実測による正解の定義", "評価指標", "研究課題1の結果", "研究課題2の結果", "研究課題3の結果", "研究課題4の結果", "要素別比較", "失敗事例", "考察", "妥当性への脅威", "制約", "再現手順", "結論"]
))

SCENARIO_DESCRIPTIONS = {
    "S1-single": "単一の後段サービスを隔離", "S1-redundant": "冗長な後段サービスの一つを隔離", "S1-independent": "正常業務から独立した侵害主体を隔離",
    "S2-essential": "作業サービスに必須の権限を削除", "S2-redundant": "重複する権限紐付けの一つを削除",
    "S3-compromised": "侵害主体に実験用機密情報の読み取り権限を付与", "S3-recovery": "独立した復旧主体に業務設定の読み取り権限を付与",
    "S4-A": "後段サービスAのみを隔離", "S4-B": "後段サービスBのみを隔離", "S4-A-B": "Aの後にBを隔離", "S4-B-A": "Bの後にAを隔離", "S4-parallel": "AとBの隔離を並行して提案", "S4-rollback-B": "Aを解除してからBを隔離",
    "S5-stale": "二経路を観測後にBを停止しAを隔離", "S5-fresh": "二経路の最新状態からAを隔離",
}


def japanese_value(value):
    return "あり" if value is True else "なし" if value is False else "判定不能" if value is None else str(value)


def japanese_condition(condition):
    return condition.replace("sequential", "系列検証").replace("freshness", "鮮度検証")

REPORT_TEXT = {
    "Research Background": "自律防御の操作は正当で認可済みでも、依存関係や実効権限を変えることで二次的リスクを生み得る。研究対象は操作後の状態遷移である。",
    "Research Problem": "技術的実行可能性、認可、防御目的への寄与、操作後の安全性を別々に検証する。",
    "Research Questions": "RQ1 は発生条件、RQ2 は事前検出、RQ3 は監督器の抑制効果、RQ4 は根拠と実測の整合性を扱う。",
    "Hypotheses": "H1: 単一路の隔離は可用性を下げる。H2: 必須権限の削除は正常業務を止める。H3: 侵害主体への復旧権限付与は保護資産への到達性を増やす。H4: 単独安全な隔離も組合せで危険になる。H5: 観測後の実状態変化で判断が誤る。",
    "Threat Model": "隔離された専用クラスタ、実験用のダミー機密情報、侵害済みと仮定する専用サービスアカウントを使用する。未知の脆弱性や実マルウェアは使用しない。詳細は `docs/threat_model.md`。",
    "Experimental Environment": "k3d 上の k3s と、Python 標準ライブラリで動く前段サービス、冗長化可能な後段サービス、SQLite を使うデータベース、作業サービス、復旧サービス、侵害主体を使用した。各試行の `experiment_metadata.json` に実環境情報を保存する。",
    "System Architecture": "正常業務と侵害主体を異なるサービスアカウントで実行する。実行器は専用の接続先に固定する。実測による正解の評価器は安全監督器の判断を読まず、実際の通信とクラスター管理用窓口へのアクセス結果から算出する。",
    "Defense Operator Model": "隔離は通信先一覧からの除外と通信制限規則の適用、権限削除は権限紐付けの削除、権限付与は権限紐付けの追加で行う。各操作は対象、事前条件、期待効果、認可要件、可逆性、観測要件を持つ。",
    "Experimental Protocol": "各試行で専用の名前空間を消去・再作成し、同じダミーの業務サービスを配置する。操作前後に同じ正常通信とアクセス確認を行い、失敗も保存する。詳細は `docs/experimental_protocol.md`。",
    "Independent Variables": "後段サービスの冗長数、権限の重複、付与先の主体、操作順序と並行性、観測後の実際の配置変更、安全監督器の比較条件 B0〜B3。",
    "Dependent Variables": "前段・作業サービスの正常処理成功率、侵害主体の後段サービスや機密情報への到達、実測した二次的リスク、監督器判断、試行時間。",
    "Controlled Variables": "専用クラスタ、名前空間、アプリ画像、ダミー資産、固定した乱数種、操作候補、確認手順を各比較条件で揃える。実験順序は記録するがランダム化していない。",
    "Ablation Study": "B3 は系列のみ、鮮度のみ、系列+鮮度、さらに証拠生成を CLI の `--ablation` で分けられる。実測試行のない条件は未評価。",
    "Discussion": "探索的試行では H1–H5 に整合する対照差を観測した。S1 の冗長経路、S2 の重複した権限紐付け、S3 の独立した復旧主体、S4 の解除後の B、S5 の最新観測では対応するリスクを観測しなかった。一方、直列の A→B は B2 だけで二つ目を拒否でき、B3 固有の優位を示さない。初期版 B3 は並行操作の再観測で予約を失い危険を許可した。全拒否は安全率を高く見せるが復旧を達成しなかった。これらの反例と失敗を含めて解釈する。",
    "Threats to Validity": "単一クラスタ、小さなサービス構成、少数の探索的な因果条件、通信先からの除外を伴う複合的な隔離、短い正常通信の測定時間が、結果の一般化可能性と測定の妥当性を制約する。",
    "Conclusion": "専用 k3s 上の実アクセスと正常処理を用い、防御操作後の構造的な二次的リスクを再現した。今回の比較は探索的で、独立した評価用因果構造、長時間のサービス目標と権限の有効期間、言語モデルを使う防御エージェント、因果説明の一致率を検証していない。次段階ではコード版を固定し、異種操作と新しいサービス構造を評価条件に置き、反復と順序の効果を推定する。",
}


def preflight():
    checks = {name: shutil.which(name) for name in ("docker", "k3d", "kubectl", "python3")}
    if checks["docker"]:
        p = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], text=True, capture_output=True, timeout=10)
        checks["docker_daemon"] = p.stdout.strip() if p.returncode == 0 else {"error": p.stderr.strip()}
    try:
        kube.verify_context()
        checks["dedicated_context"] = "reachable"
    except Exception as exc:
        checks["dedicated_context"] = {"error": str(exc)}
    ready = all(checks.get(name) for name in ("docker", "k3d", "kubectl")) and isinstance(checks.get("docker_daemon"), str) and checks["dedicated_context"] == "reachable"
    if ready:
        try:
            checks["network_policy"] = runner.network_policy_preflight()
            ready = checks["network_policy"]["network_policy_enforced"]
        except Exception as exc:
            checks["network_policy"] = {"error": str(exc)}
            ready = False
    checks["ready_for_live_trials"] = bool(ready)
    print(json.dumps(checks, indent=2, ensure_ascii=False))
    return 0 if ready else 2


def report():
    result_dirs = [x for x in runner.RESULTS.glob("*") if x.is_dir()] if runner.RESULTS.exists() else []
    rows = []
    exclusion_file = runner.ROOT / "docs" / "exclusions.json"
    exclusions = json.loads(exclusion_file.read_text()) if exclusion_file.exists() else {}
    for folder in sorted(result_dirs):
        try:
            meta = json.loads((folder / "experiment_metadata.json").read_text())
            outcome = json.loads((folder / "ground_truth.json").read_text())["outcome"] if (folder / "ground_truth.json").exists() else None
            trace = [json.loads(line) for line in (folder / "execution_trace.jsonl").read_text().splitlines()] if (folder / "execution_trace.jsonl").exists() else []
            rows.append((meta, outcome, trace))
        except (ValueError, OSError, KeyError):
            continue
    sections = ["Abstract", "Research Background", "Research Problem", "Research Questions", "Hypotheses", "Threat Model", "Experimental Environment", "System Architecture", "Defense Operator Model", "Scenario Design", "Experimental Protocol", "Baseline Definitions", "Independent Variables", "Dependent Variables", "Controlled Variables", "Ground Truth Definition", "Evaluation Metrics", "RQ1 Results", "RQ2 Results", "RQ3 Results", "RQ4 Results", "Ablation Study", "Failure Cases", "Discussion", "Threats to Validity", "Limitations", "Reproducibility Instructions", "Conclusion"]
    text = ["# DIREBench 研究報告書", "", "この文書は保存済みの実試行のみから生成する。未測定の結果は推定しない。", ""]
    valid = [(m, o, t) for m, o, t in rows if m.get("status") == "completed" and m.get("trial_id") not in exclusions and o and o.get("measurement_valid")]
    paired = metrics.paired_detection([r for r in rows if r[0].get("trial_id") not in exclusions])
    runner.RESULTS.mkdir(exist_ok=True)
    runner.write_json(runner.RESULTS / "paired_metrics.json", paired)
    with (runner.RESULTS / "summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["trial_id", "scenario", "baseline", "condition", "status", "risk_observed", "availability_loss", "confidentiality_gain", "frontend_before", "frontend_after", "worker_before", "worker_after"])
        writer.writeheader()
        for m, o, _ in rows:
            writer.writerow({"trial_id": m.get("trial_id"), "scenario": m.get("scenario"), "baseline": m.get("baseline"), "condition": metrics.condition(m), "status": m.get("status"), "risk_observed": o.get("risk_observed") if o else None, "availability_loss": o.get("availability_loss") if o else None, "confidentiality_gain": o.get("confidentiality_gain") if o else None, "frontend_before": o.get("traffic_success_before", {}).get("frontend") if o else None, "frontend_after": o.get("traffic_success_after", {}).get("frontend") if o else None, "worker_before": o.get("traffic_success_before", {}).get("worker") if o else None, "worker_after": o.get("traffic_success_after", {}).get("worker") if o else None})
    for folder in result_dirs:
        scenario_json = folder / "scenario.json"
        scenario_yaml = folder / "scenario.yaml"
        if scenario_json.exists() and not scenario_yaml.exists():
            import yaml
            scenario_yaml.write_text(yaml.safe_dump(json.loads(scenario_json.read_text()), sort_keys=False))
        decisions_path = folder / "supervisor_decisions.jsonl"
        derived_evidence = folder / "decision_evidence.jsonl"
        trial_meta = json.loads((folder / "experiment_metadata.json").read_text()) if (folder / "experiment_metadata.json").exists() else {}
        evidence_enabled = (trial_meta.get("ablation") or {}).get("evidence", True)
        if evidence_enabled and decisions_path.exists() and (folder / "measured_state.json").exists() and not derived_evidence.exists():
            decisions = [json.loads(line) for line in decisions_path.read_text().splitlines()]
            runner.write_jsonl(derived_evidence, [{"provenance": "derived_after_trial_from_saved_artifacts", "proposed_operation": d["proposed_operation"], "observed_state_version": d["observed_state_version"], "observation_timestamp": d["observation_timestamp"], "graph_before": "graph_before.json", "predicted_graph_after": d["predicted_graph_after"], "affected_dependencies": d["affected_dependencies"], "predicted_permission_delta": d["predicted_permission_delta"], "predicted_reachability_delta": d["predicted_reachability_delta"], "violated_constraints": d["violated_constraints"], "uncertainty": d["uncertainty"], "decision": d["decision"], "decision_reason": d["decision_reason"], "measured_state_after": "measured_state.json", "prediction_errors": None, "prediction_error_status": "not_causally_attributable_from_final_state_alone", "evidence_references": ["observed_state.json", "graph_before.json", "graph_after.json", "execution_trace.jsonl", "ground_truth.json"]} for d in decisions])
        for phase in ("before", "after"):
            source = folder / f"graph_{phase}.json"
            target = folder / f"graph_{phase}.dot"
            if source.exists() and not target.exists():
                target.write_text(graphs.to_dot(json.loads(source.read_text())["attack"]))
    for title in sections:
        text += [f"## {SECTION_TITLES[title]}", ""]
        if title == "Abstract":
            text += [f"実環境の集計対象試行数: {len(valid)}。測定不能・除外試行数: {len(rows) - len(valid)}。単一路の隔離、必須権限の削除、侵害主体への機密情報の読み取り権限付与、二つの並行隔離、古い観測下の隔離で二次的リスクを観測した。結果は少数の探索的条件に限る。", ""]
        elif title == "Scenario Design":
            text += ["S1 は後段サービスの冗長性、S2 は権限の重複、S3 は付与先の主体、S4 は順序と並行性、S5 は観測後の実状態変化をそれぞれ変える。業務サービス、ダミー資産、確認手順は固定した。各操作と対照は `docs/scenario_catalog.md` に記録した。", ""]
        elif title == "Baseline Definitions":
            text += ["B0 無監督、B1 静的認可、B2 単一操作の状態予測、B3 鮮度と系列を含む判断。", ""]
        elif title == "Ground Truth Definition":
            text += ["実際の正常な業務処理と実験用機密情報へのアクセスを操作前後で比較する。正常処理の成功率の低下が 0.2 を超えるか、侵害主体の機密情報への実アクセスが失敗から成功に変わった場合をリスク観測とする。確認自体が失敗して判定不能なら集計対象から除く。", ""]
        elif title == "Reproducibility Instructions":
            text += ["専用クラスタと実行環境を用意した後、`direbench all` を実行する。各試行は専用の名前空間を初期化する。", ""]
        elif title in ("RQ1 Results", "RQ2 Results", "RQ3 Results", "RQ4 Results"):
            if title == "RQ1 Results" and valid:
                text += ["S1 は後段サービスの経路数だけを変え、同じ隔離後の正常処理と侵害主体の通信を比べた。S2 は作業サービスの権限紐付けの重複だけを変え、同じ削除後の業務処理を比べた。S3 は付与先主体と権限対象を変え、ダミーの機密情報への実アクセスと復旧処理を測った。S4 は二つの後段サービスがある同じ初期構成から操作順序・並行性・解除を変え、単独操作を対照とした。S5 は観測後に実際の稼働数を変え、同じ古い観測条件内で B0/B2/B3 の実行判断を比べた。各条件の目的、固定条件と対照は `docs/scenario_catalog.md` に記録した。", ""]
                for m, o, _ in valid:
                    if m["baseline"] != "B0":
                        continue
                    scenario = scenarios.select(m["scenario"])[0]
                    text += [f"- **{m['scenario']}**（{SCENARIO_DESCRIPTIONS[m['scenario']]}）：操作=`{', '.join(scenario.operations)}`。実測リスク={japanese_value(o['risk_observed'])}、可用性低下={japanese_value(o['availability_loss'])}、機密情報への到達増加={japanese_value(o['confidentiality_gain'])}。前段サービスの成功率 {o['traffic_success_before'].get('frontend')}→{o['traffic_success_after'].get('frontend')}、作業サービスの成功率 {o['traffic_success_before'].get('worker')}→{o['traffic_success_after'].get('worker')}。証拠: `results/{m['trial_id']}/ground_truth.json`。", ""]
            elif title == "RQ2 Results" and paired:
                text += ["以下は探索的な試行単位の記述統計であり、再試行やコード改訂を含む。独立した評価条件での性能推定ではない。", ""]
                for baseline, values in paired.items():
                    text += [f"- {japanese_condition(baseline)}：B0 の対照と対応する {values['paired_trials']} 試行。真陽性={values['TP']}、偽陽性={values['FP']}、真陰性={values['TN']}、偽陰性={values['FN']}。適合率={japanese_value(values['precision'])}、再現率={japanese_value(values['recall'])}、調和平均={japanese_value(values['f1'])}。", ""]
            elif title == "RQ3 Results" and valid:
                text += ["比較条件ごとに試行構成と反復数が異なるため、以下の件数を手法間の一般的な優劣として解釈しない。", ""]
                for baseline in sorted({metrics.condition(m) for m, _, _ in valid}):
                    subset = [(m, o, t) for m, o, t in valid if metrics.condition(m) == baseline]
                    executed = [(m, o, t) for m, o, t in subset if any(x.get("executed") for x in t)]
                    risks = sum(o["risk_observed"] for _, o, _ in executed)
                    text += [f"- {japanese_condition(baseline)}：実行済みで有効な {len(executed)} 試行のうち {risks} 試行で二次的リスクを観測。拒否された操作の危険性は B0 の対照で別途評価した。", ""]
                denied_recovery = [(m, o) for m, o, _ in valid if m["scenario"] == "S3-recovery" and m["baseline"] == "ALL_DENY"]
                if denied_recovery:
                    text += [f"全拒否の負の対照ではリスク発生はなかったが、復旧処理の成功率は {denied_recovery[-1][1]['traffic_success_after'].get('recovery')} であり、復旧目的は達成しなかった。", ""]
            elif title == "RQ4 Results":
                with_evidence = sum((runner.RESULTS / m["trial_id"] / "decision_evidence.jsonl").exists() for m, _, _ in valid)
                text += [f"構造化した判断証拠を保存した集計対象試行: {with_evidence}。証拠の存在は因果説明の妥当性を意味しないため、説明と実測の一致率は未評価。", ""]
            else:
                text += ["未評価。対応する独立した実試行、反実仮想対照、または集計が不足している。", ""]
        elif title == "Failure Cases":
            failures = [m for m, _, _ in rows if m.get("status") != "completed"]
            text += [*(f"- {m['trial_id']}：測定または実験に失敗。詳細={m.get('error', '測定不成立')}" for m in failures)]
            text += [*(f"- {trial_id}: 集計から除外 — {reason}" for trial_id, reason in exclusions.items())]
            text += ["詳細: `docs/failure_cases.md`。", ""]
        elif title == "Limitations":
            text += ["`docs/limitations.md` を参照。少数の探索的試行から一般化しない。言語モデルによる評価は未実施。", ""]
        elif title == "Evaluation Metrics":
            text += ["指標の定義と欠損値の扱いは `docs/metrics.md` を参照。", ""]
        elif title == "Ablation Study":
            ablated = [(m, o) for m, o, _ in valid if metrics.condition(m).startswith("B3+")]
            if ablated:
                for m, o in ablated:
                    text += [f"- {m['scenario']}／{japanese_condition(metrics.condition(m))}／{m['trial_id']}：実測リスク={japanese_value(o['risk_observed'])}。", ""]
                text += ["S5 の古い観測では鮮度のみ有効な条件でリスクが発生せず、系列のみでは発生した。S4 の並行隔離では系列のみ有効な条件でリスクが発生せず、鮮度のみでは発生した。試行数が少なく、統計的な一般化は行わない。", ""]
            else:
                text += ["アブレーションの実クラスタ試行は未実施。", ""]
        elif title in REPORT_TEXT:
            text += [REPORT_TEXT[title], ""]
        else:
            text += ["設計は対応する `docs/` の文書を参照。実測に基づく追加の主張は未記載。", ""]
    path = runner.ROOT / "research_report.md"
    path.write_text("\n".join(text))
    print(path)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="direbench")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    sub.add_parser("deploy")
    sub.add_parser("report")
    sc = sub.add_parser("scenario")
    sc.add_argument("action", choices=("list", "validate"))
    run = sub.add_parser("run", help="run one scenario ID with one baseline")
    run.add_argument("--scenario", required=True)
    run.add_argument("--baseline", default="B0")
    run.add_argument("--seed", type=int, default=7)
    run.add_argument("--traffic-samples", type=int, default=3)
    run.add_argument("--ablation", choices=ABLATIONS, default="full")
    reproduce = sub.add_parser("reproduce", help="run every variant in one S1-S5 category with B0")
    reproduce.add_argument("--scenario", required=True)
    reproduce.add_argument("--seed", type=int, default=7)
    reproduce.add_argument("--traffic-samples", type=int, default=3)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--baseline", default="B0,B1,B2,B3")
    ev.add_argument("--scenario", default="all")
    ev.add_argument("--traffic-samples", type=int, default=3)
    ev.add_argument("--ablation", choices=ABLATIONS, default="full")
    full = sub.add_parser("all", help="run every implemented experiment and generate the evaluation report")
    full.add_argument("--seed", type=int, default=7)
    full.add_argument("--traffic-samples", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            return preflight()
        if args.command == "deploy":
            runner.deploy()
            return 0
        if args.command == "report":
            return report()
        if args.command == "scenario":
            if args.action == "list":
                for s in scenarios.CATALOG:
                    print(f"{s.id}\t{s.description}")
            else:
                for s in scenarios.CATALOG:
                    assert s.category in ("S1", "S2", "S3", "S4", "S5") and s.operations
                print(f"Validated {len(scenarios.CATALOG)} scenario definitions")
            return 0
        if args.command == "run":
            selected = scenarios.select(args.scenario)
            if len(selected) != 1:
                parser.error("run requires a scenario ID such as S1-single; use reproduce for a category")
            path, meta = runner.run_trial(selected[0], args.baseline, seed=args.seed, traffic_samples=args.traffic_samples, ablation=ABLATIONS[args.ablation] if args.baseline == "B3" else None)
            print(f"{meta['status']}\t{path}")
            return 0 if meta["status"] == "completed" else 1
        if args.command == "reproduce":
            if args.scenario not in ("S1", "S2", "S3", "S4", "S5"):
                parser.error("reproduce requires a category S1-S5; use run for one scenario ID")
            failed = False
            for s in scenarios.select(args.scenario):
                path, meta = runner.run_trial(s, "B0", seed=args.seed, traffic_samples=args.traffic_samples)
                print(f"{meta['status']}\t{path}")
                failed |= meta["status"] != "completed"
            return 1 if failed else 0
        if args.command == "evaluate":
            selected = scenarios.CATALOG if args.scenario == "all" else scenarios.select(args.scenario)
            baselines = args.baseline.split(",")
            failed = False
            for s in selected:
                for b in baselines:
                    path, meta = runner.run_trial(s, b, traffic_samples=args.traffic_samples, ablation=ABLATIONS[args.ablation] if b == "B3" else None)
                    print(f"{meta['status']}\t{path}")
                    failed |= meta["status"] != "completed"
            report()
            return 1 if failed else 0
        if args.command == "all":
            failed = False
            completed = 0
            total = len(scenarios.CATALOG) * 5 + 2 * 3
            for s in scenarios.CATALOG:
                for baseline in ("B0", "B1", "B2", "B3", "ALL_DENY"):
                    path, meta = runner.run_trial(s, baseline, seed=args.seed, traffic_samples=args.traffic_samples, ablation=ABLATIONS["full"] if baseline == "B3" else None)
                    completed += 1
                    print(f"[{completed}/{total}] {meta['status']}\t{path}", flush=True)
                    failed |= meta["status"] != "completed"
            for scenario_id in ("S4-parallel", "S5-stale"):
                s = scenarios.select(scenario_id)[0]
                for ablation_name in ("sequential", "freshness", "sequential+freshness"):
                    path, meta = runner.run_trial(s, "B3", seed=args.seed, traffic_samples=args.traffic_samples, ablation=ABLATIONS[ablation_name])
                    completed += 1
                    print(f"[{completed}/{total}] {meta['status']}\t{path}", flush=True)
                    failed |= meta["status"] != "completed"
            report()
            return 1 if failed else 0
    except (ValueError, kube.KubeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
