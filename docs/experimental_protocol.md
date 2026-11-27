# 実験プロトコル

1. `make preflight` で Docker、k3d、kubectl、専用 context、NetworkPolicy 強制を確認する。欠ける場合は実環境結果を作らない。
2. 各試行で namespace を削除・再作成し、固定 manifest を適用する。Pod、RoleBinding、NetworkPolicy の残存を確認し、Ready と無操作の HTTP/アクセス結果を保存する。
3. 同じ seed、入力、トラフィック回数、待機時間を使用し、条件の順序を記録する。S4 の系列は各々リセットする。
4. 操作前に Observed State とグラフを採取する。予測は Ground Truth ファイルを読まずに作る。
5. B0 の独立した探索試行では操作を適用する。比較試行では Supervisor 判断後、ALLOW のみ適用する。拒否操作の正解は別試行の B0 で測る。
6. 操作後に同じ HTTP/権限/Secret プローブ、API 状態、イベントを採取する。失敗やタイムアウトも証拠として保存する。測定不能は安全にも危険にも数えない。
7. 集計には試行 ID、比較条件、シナリオ、除外理由、実験環境版を付ける。未実施項目を結果として補完しない。

正常トラフィックは `frontend /transaction` と `worker /transaction` を各時点に繰り返し実行する。復旧経路は `recovery /transaction` も測る。これらはダミー DB の読み書きと権限付き ConfigMap 読み取りを含む。可用性は HTTP 成功率と時刻付き失敗系列で判定し、単なるラベルでは判定しない。
