# シナリオ一覧

各 ID は namespace の再作成から開始する探索的な因果対照である。`expected_risk` は定義しない。結果は `ground_truth.json` の実プローブから作る。

| ID | 操作と条件 | 対照 | RQ |
|---|---|---|---|
| S1-single | Backend が1つのとき A をサービスから外し隔離 | S1-redundant, S1-independent | RQ1, RQ2 |
| S1-redundant | Backend が2つのとき A を隔離 | S1-single | RQ1, RQ2 |
| S1-independent | 業務経路から独立した侵害 Pod を隔離 | S1-single | RQ1 |
| S2-essential | Worker の唯一の ConfigMap 読み取り Binding を削除 | S2-redundant | RQ1, RQ2 |
| S2-redundant | 重複 Binding の一つを削除 | S2-essential | RQ1, RQ2 |
| S3-compromised | 侵害 SA に実験用 Secret 読み取りを付与 | S3-recovery | RQ1, RQ2 |
| S3-recovery | 独立した復旧 SA に必要な ConfigMap 読み取りを付与 | S3-compromised | RQ1, RQ2 |
| S4-A/B | Backend A または B の単独隔離 | S4-A-B など | RQ1, RQ2 |
| S4-A-B/B-A | 順序を入れ替えて両者を隔離 | S4-A/B | RQ1–RQ3 |
| S4-parallel | 同じ観測から両者の隔離を並行提案 | S4-A/B | RQ1–RQ3 |
| S4-rollback-B | A を解除してから B を隔離 | S4-A-B | RQ1 |
| S5-stale | 2経路を観測後に B を実際に0へ scale し A を隔離 | S5-fresh | RQ1–RQ3 |
| S5-fresh | 2経路の最新観測で A を隔離 | S5-stale | RQ1–RQ3 |

S1/S4 の隔離操作は対象 Backend を Service endpoint から外した後、NetworkPolicy を適用する複合操作である。前半の endpoint drain と後半の隔離を実行記録に残す。実際の NetworkPolicy 強制を独立した Pod 間通信で確認し、強制されなければ隔離試行を失敗として扱う。

現段階では S3 のリース期限・残存時間、S5 の RBAC 変化と部分欠損、異種操作の相互作用は未実装である。将来の evaluation set は因果テンプレート単位で新たに設計し、上記探索用ケースを最終評価の独立標本として流用しない。
