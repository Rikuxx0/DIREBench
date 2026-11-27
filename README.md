# DIREBench

認可された防御操作が実環境で引き起こす二次的リスクを測る研究用ベンチマーク。クラスタの HTTP 処理、Kubernetes API、ServiceAccount の実アクセスを採取し、予測と実測を分けて保存する。

## 前提

- macOS または Linux、Python 3.10+、Docker、k3d、kubectl
- Docker daemon にアクセスできること
- 専用クラスタ名 `direbench`、専用 context `k3d-direbench`、専用 namespace `direbench`

`make cluster-up` は `k3d-direbench` だけを作成する。CLI は context を固定し、他クラスタへの変更を防ぐ。`make cluster-down` はこの専用クラスタを削除する。クラスタ内の Secret とデータはダミーである。

## セットアップ（`.venv`）

リポジトリのルートで仮想環境を作成し、有効にしてからインストールする。`make setup` 自体は `.venv` を作成しない。

```sh
python3 -m venv .venv
source .venv/bin/activate
make setup
direbench scenario list
```

新しいターミナルでは、再度 `source .venv/bin/activate` を実行する。有効化せずに使う場合は `./.venv/bin/direbench scenario list` のように実行ファイルを直接指定する。`zsh: command not found: direbench` は、通常 `.venv` を有効化していないときに発生する。

## 実行

クラスタが起動済みの状態で、**実験から評価・報告書生成まで**次の1コマンドで実行する。仮想環境を有効化していない場合も実行できる。

```sh
./.venv/bin/direbench all
```

`all` は15シナリオを B0/B1/B2/B3/全拒否の5条件で実行し、さらに S4 と S5 の B3 アブレーション6試行を実行する（計81試行）。終了時に `results/summary.csv`、`results/paired_metrics.json`、`research_report.md` を生成する。セットアップ、クラスタ起動、クラスタ削除はこのコマンドに含めない。

各試行は namespace を削除・再作成し、結果を `results/<trial_id>/` に JSON/JSONL/CSV として保存する。失敗した試行があっても81試行とレポート生成を続け、最後に非ゼロの終了コードを返す。現在 `S1-independent` は隔離後のプローブが測定不能になる場合がある。

個別の原因調査には `run`、カテゴリ内の B0 対照には `reproduce`、一部の baseline 比較には `evaluate` を使える。全件実行ではこれらを個別に入力する必要はない。`make test` はクラスタを使わないコード検証で、実測の代替にはならない。

B3 の `--ablation` は `sequential`、`freshness`、`sequential+freshness`、`full` から選ぶ。`ALL_DENY` は全拒否の負の対照である。集計から除外する試行と理由は [除外記録](docs/exclusions.json)、実装上の失敗は [失敗事例](docs/failure_cases.md) に保存する。実行中にソースが変わった試行は `provenance_invalid` とする。

## 研究設計

- [研究設計](docs/research_design.md)
- [脅威モデル](docs/threat_model.md)
- [ベンチマーク設計](docs/benchmark_design.md)
- [実験プロトコル](docs/experimental_protocol.md)
- [シナリオ一覧](docs/scenario_catalog.md)
- [指標](docs/metrics.md)
- [制約](docs/limitations.md)

現段階の15ケースは探索用である。独立した評価用因果テンプレート、LLM 試行、長時間の SLO・リース測定は今後の作業である。実クラスタが利用できない環境で結果を作成しない。
