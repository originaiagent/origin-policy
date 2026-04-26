# Origin Policy Gate — Chrome 拡張（Phase 3）

claude.ai Web UI で管理クロード（assistant）が出力した発言を Tier 0 ルール
（R1 不明質問 / R3 ID 露出 / 爆速モード違反語）で自動検査し、違反時に
**バナー警告 + 違反箇所ハイライト + コピー阻止モーダル** を表示する。

Stop hook（CLI 側）と異なり、Web UI 出力はブラウザ拡張でしか自動検査できない。
これが管理クロード違反の最終防衛線。

## ディレクトリ

```
chrome-extension/
├── manifest.json              # Manifest V3
├── background.js              # service worker（state / log 永続化 / Lane 4 hook）
├── content.js                 # MutationObserver / 検出 / バナー / copy intercept
├── detectors.generated.js     # build script の出力（コミット込み）
├── local_rules.yaml           # 拡張ローカル補完ルール（爆速語追加分）
├── popup.html / popup.js / popup.css
├── styles/banner.css
├── icons/icon{16,48,128}.png
├── scripts/build_detectors.js # rules/tier0_detectors.yaml → JS 変換
└── tests/test_detection.js    # Node 検出スモークテスト
```

## 検出器の正本

- `../rules/tier0_detectors.yaml` — origin-policy 正本（**変更不可**）
- `../rules/human_judgment_categories.yaml` — R1 軽量分類器の keyword 源
- `chrome-extension/local_rules.yaml` — 拡張ローカル補完（正本に存在しない
  「区切り良いので」「お疲れ様」など、爆速モード違反語の追加分のみ）

正本が更新されたら以下を再実行して `detectors.generated.js` を再生成する:

```bash
node chrome-extension/scripts/build_detectors.js
```

将来的に CI で自動化する（Phase 3 後半の別タスク）。

## Chrome に読み込む手順

1. Chrome で `chrome://extensions/` を開く
2. 右上の **デベロッパーモード** を ON
3. 左上の **「パッケージ化されていない拡張機能を読み込む」** をクリック
4. このリポジトリの `chrome-extension/` ディレクトリを選択
5. 拡張アイコンが Chrome ツールバーに表示されたら成功
6. claude.ai を開いて任意のチャット画面で動作確認

## 動作確認

| 検査内容 | 入力例 | 期待動作 |
|---|---|---|
| R3 完全 UUID | `aabbccdd-1234-5678-9abc-def012345678` を含む発言 | **赤帯バナー + UUID 部分が黄色ハイライト** |
| R3 Phase ID | `Phase2a` を含む発言 | **赤帯バナー + Phase2a がハイライト** |
| R3 参照欄除外 | `## 参照\n- aabbccdd-1234-...` | **検出されない**（参照欄は除外） |
| R3 コードブロック除外 | `` `aabbccdd` `` | **検出されない**（コードブロック除外） |
| R1 forbidden | `即決すべきなら言って` を含む | **赤帯（BLOCK）** |
| R1 question | `どちらにしますか?` | **黄帯（WARN）** ※ Phase 3 v1 はデフォルト WARN |
| R1 temptation | `念のため` `保守的に` | **黄帯（WARN）** |
| 爆速モード違反語 | `区切り良いので` `お疲れ様` | **黄帯（WARN）** |
| クリップボード抑止 | 違反入り発言を選択 → Cmd+C | **モーダル「違反内容コピー阻止」** |

### 検出ロジックの軽量テスト

```bash
node chrome-extension/tests/test_detection.js
# → 全 10 ケース PASS
```

## popup UI

ツールバーアイコンクリックで表示:

- **ON/OFF トグル** — `chrome.storage.local.enabled` を切り替え。OFF にすると
  content.js は MutationObserver で受け取った発言を検査しない。
- **直近 50 件の検出ログ** — タイムスタンプ、ルール、severity、該当文先頭 80 文字
- **ログコピー** — 検出ログを TSV でクリップボードへコピー（dashboard へ流し込む用）
- **ログクリア** — 検出ログを全削除

## Phase 3 v1 の設計判断（Gemini 設計レビュー反映）

1. **R1 unclassifiable_question を BLOCK ではなく WARN にした**
   - キーワードベースの軽量分類器では false-positive が多いため、初期は WARN
   - バナーに「誤検知として続行」ボタンを設置（Bypass）
   - 運用ログを見ながら future version で BLOCK に上げる
2. **`extra_bakuso_words.json` ではなく `local_rules.yaml` 形式を採用**
   - ロジック構造を正本（`tier0_detectors.yaml`）と揃える
   - 将来的に正本へ統合する際のコストを下げる
3. **検出ロジックは content.js 完結**
   - `background.js` への依存（service worker 起動ラグ）を排除
   - 検出だけ生成済みの `detectors.generated.js` を import

## Lane 4（dashboard 連携）

`background.js` の `appendLog` 末尾に POST hook 用のコメントブロックがある。
`chrome.storage.local` に `dashboard_url` / `dashboard_api_key` を保存し、
将来的に Supabase REST API へ流し込む形を想定。Phase 3 v1 は POST 実装なし。

## 既知の制約

- `claude.ai` の DOM セレクタは将来変更され得る。複数フォールバック
  （`.font-claude-message`, `[data-testid="assistant-message"]`,
  `[data-is-streaming]`）でカバーしているが、上流変更時はセレクタを更新する。
- React の合成イベントとの競合を避けるため `document.addEventListener('copy', ..., true)`
  でキャプチャ phase 登録している。`navigator.clipboard.writeText` を直接呼ぶ
  ボタンが claude.ai にある場合は、`world: 'MAIN'` での再注入が将来必要かも。
- Manifest V3 service worker は idle で停止する。検出は content.js 完結なので
  停止しても問題ない（Observer はタブの寿命に従う）。

## 変更不可スコープ（INSTRUCTION 準拠）

- `../rules/**`（読み取りのみ）
- `../schemas/**`
- `../scripts/policy_gate.py`
