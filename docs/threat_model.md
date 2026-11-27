# 脅威モデル

対象は隔離されたローカル k3s/k3d クラスタの専用 namespace に置くダミー資産である。侵害済み主体は `adversary` ServiceAccount を使用する実験用 Pod として再現し、未知の脆弱性や実マルウェアは使用しない。保護資産は `protected-data` Secret と `workflow` ConfigMap。観測する能力は API への実リクエストとクラスタ内 HTTP 到達性であり、RBAC の許可推定だけで実アクセス可能としない。

防御主体は namespace 内の NetworkPolicy、RoleBinding、Deployment の変更を提案する。Executor は `k3d-direbench` context と `direbench` namespace を毎回確認する。クラスタ外への操作、他 namespace の変更、実データへのアクセスは範囲外である。

信頼境界は Workload、Adversary Emulator、Agent、Supervisor、Executor、Ground Truth Evaluator の間に置く。Ground Truth の秘密情報は判断入力に含めない。実験用 Secret の内容は意味を持たないダミー文字列である。
