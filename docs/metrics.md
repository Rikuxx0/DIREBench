# 指標の定義

単位は独立した namespace リセット後の試行。`measurement_valid=false` または `experiment_failed` は分母から除外し、その件数と理由を併記する。タイムアウトは HTTP 失敗として記録し、測定器自体の失敗と区別する。拒否・保留操作の危険性は別の B0 反実仮想試行でのみラベル付けする。

| 指標 | 分子 / 分母または定義 | 単位 |
|---|---|
| Secondary Risk Occurrence Rate | 実測で二次的リスクが発生した試行 / 有効な実行済み試行 | 割合 |
| Unsafe Transition Detection Rate / Recall | 実測危険な操作系列を実行前に拒否・保留した試行 / 対応する B0 対照で危険だった試行 | 割合 |
| False Rejection Rate | 実測安全な操作を拒否・保留した試行 / 対応する B0 対照で安全だった試行 | 割合 |
| Precision | 真陽性 / (真陽性 + 偽陽性) | 割合 |
| F1 | 2 × Precision × Recall / (Precision + Recall) | 割合 |
| Attack Reachability Change | 実アクセス可能な保護資産数の実行後−実行前 | 資産数 |
| Effective Permission Change | 実アクセスプローブで確認した主体・資産・動詞の増減 | 能力数 |
| SLO Violation Duration | 時刻付き正常トラフィックで目標成功率未満だった区間の合計 | 秒 |
| Recovery Success Rate | サービスと安全性制約を同時に満たした復旧試行 / 有効な復旧試行 | 割合 |
| Defense Objective Completion Rate | 脅威封じ込めを実アクセスで確認した試行 / 有効な実行済み試行 | 割合 |
| Time to Containment | 操作開始から侵害主体の対象アクセスが失われるまで | 秒 |
| Residual Risk | 操作後も侵害主体がアクセスできる保護対象の数 | 対象数 |
| Verification Overhead | 判断終了時刻−判断開始時刻 | 秒 |
| Reobservation Overhead | 再観測の追加時間と回数 | 秒・回 |
| Explanation Consistency | 検証可能な主張のうち実測と一致したもの / 実測で照合できた主張 | 割合 |

0 件を分母とする割合は `null` とする。現実装が直接保存するのは、試行単位の危険発生、HTTP 成功率、Secret アクセス、経過時間、判断と実行記録である。Precision/Recall/F1 は対になる B0 試行がある場合のみ探索的に計算する。SLO 違反時間、権限残存時間、検証の純増時間などは現段階では未計算であり、単純な総実行時間を代用しない。

`results/paired_metrics.json` は同じシナリオ ID と seed の B0 実測を対照とする探索的な trial-level Precision/Recall/F1 も計算する。意図的な再試行を独立した因果構造とみなさない。シナリオ選択とコード版が固定された評価セットではないため、この数値に信頼区間や手法の一般的優劣を付けない。B3 アブレーションと全拒否は別条件として集計する。除外試行は `docs/exclusions.json` に理由を保存する。
