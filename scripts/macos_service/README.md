# Policy Gate macOS Quick Action

選択テキストを右クリック → "Policy Gate で検査" → 通知センターで結果表示。

## 構成

| ファイル | 役割 |
| --- | --- |
| `PolicyGateCheck.workflow/` | Automator Quick Action（Service）本体 |
| `install.sh` | `~/Library/Services/` にコピー＋環境変数を `launchctl setenv` |
| `uninstall.sh` | サービスを削除し `launchctl` 環境変数も解除 |
| `linux_fallback.sh` | macOS 以外向け: xclip + notify-send 版 |

## インストール

```bash
cd scripts/macos_service
./install.sh
# あるいは明示指定:
ORIGIN_POLICY_REPO=~/dev/origin-policy ORIGIN_POLICY_PYTHON=/usr/bin/python3 ./install.sh
```

`install.sh` はリポと Python インタプリタの絶対パスを `~/Library/Services/` に
コピーしたワークフローへ直接書き込む（再起動後も有効）。ソース側の `.workflow`
はプレースホルダ (`__ORIGIN_POLICY_REPO__` / `__ORIGIN_POLICY_PYTHON__`) のまま。

インストール後、`システム設定 → キーボード → キーボードショートカット → サービス` で
"Policy Gate で検査" を有効化してください（macOS Sonoma 以降は `システム設定 → キーボード →
キーボードショートカット → サービス → テキスト` 配下）。
ショートカットキー（例: ⌃⌥⌘P）を割り当てると右クリックなしで実行できる。

## 動作

1. 任意のテキストを選択（管理クロードのチャット出力など）
2. 右クリック → サービス → "Policy Gate で検査"
3. `origin_policy.check_management_output` が R1/R3/R5 検査
4. 結果を通知センターに表示
   - 違反あり: タイトル "Policy Gate: BLOCK"
   - 警告のみ: "Policy Gate: WARN"
   - 違反なし: "Policy Gate: PASS"

## アンインストール

```bash
./uninstall.sh
```

## Linux 代替

```bash
./linux_fallback.sh           # クリップボード経由
echo "テキスト" | ./linux_fallback.sh --stdin
```

## トラブルシュート

- 通知が出ない → `osascript -e 'display notification "test" with title "test"'` で通知許可を確認
- "module not found" → `/usr/bin/python3 -m pip install pyyaml jsonschema`
- パスがズレた / リポを移動した → `install.sh` を再実行（最新パスが workflow に焼かれる）
