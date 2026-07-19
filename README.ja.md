# pico-face

**AIエージェントが動くマシンに「顔」を生やすアプリ** 🥺

pico-face は、バックグラウンドで AI エージェントが動いている Raspberry Pi
（や Mac）を、感情のある小さな生き物に変えます。サービスの生死・Claude Code
のセッション・使用量の枠を見守って、ダッシュボードではなく**表情**で伝えます。

[English README](README.md)

- **光る目と9つの表情** — ひま😪 / 作業中✨ / おへんじ待ち❗ / えっへん😤 /
  あつい🥵 / 枠ピンチ💦 / トラブル＞＜ / おやすみ😴 / なでるとハート目💗
- **なつき度（たまごっち）** — 毎日なでて、いっしょにタスクをこなすと
  「はじめまして」から「ずっといっしょ」まで絆が育つ。放置すると下がる。
- **きょうのきぶん** — 日替わりで はりきり/まったり/あまえんぼう/おちゃめ/
  てれや。仕草・テンポ・セリフが変わる。
- **Claude Code 連動** — 何セッションが*作業中*で、何セッションが*あなたの
  返事待ち*かを表示（プロセスの CPU 統計のみ使用。**内容は一切読みません**）。
- **PWA** — スマホのホーム画面に追加可能。目が指を追いかける。
- **依存ゼロ** — Python 標準ライブラリのみ。HTML 1枚。ビルド不要。

## クイックスタート

```bash
git clone https://github.com/bitpackman/pico-face.git
cd pico-face
cp config.example.json config.json   # 好みに編集
python3 server.py                    # -> http://localhost:8090/
```

`?mood=idle|working|waiting|proud|hot|sweat|trouble|sleeping|heart` で全表情をプレビューできます。

## 常駐させる

**Raspberry Pi / Linux（systemd user service）**

```bash
cp deploy/pico-face.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pico-face.service
loginctl enable-linger $USER
```

**macOS（launchd）**

```bash
sed "s|__HOME__|$HOME|g" deploy/com.picoface.server.plist > ~/Library/LaunchAgents/com.picoface.server.plist
launchctl load ~/Library/LaunchAgents/com.picoface.server.plist
```

## 設定（`config.json`）

| キー | デフォルト | 説明 |
|---|---|---|
| `name` | `"pico"` | キャラクターの名前 |
| `lang` | `"en"` | UI 言語：`"en"` / `"ja"` |
| `port` | `8090` | HTTP ポート |
| `services` | `[]` | 監視するサービス。落ちると泣き顔になる |
| `tasks_dir` | `null` | `queue/ running/ done/ failed/` を持つディレクトリ（完了タスクがなつき度に加算） |
| `claude_usage` | `true` | Claude 使用量枠の表示（下記の注意参照） |
| `claude_sessions` | `true` | Claude Code セッションの CPU ベース分類 |
| `session_pattern` | `"--sdk-url"` | セッションプロセスを見つける pgrep パターン |
| `hot_temp_c` | `78` | あつがり顔になる CPU 温度（Linux のみ） |
| `sweat_usage_pct` | `85` | 焦り顔になる 5時間枠の % |
| `night_hours` | `[1, 7]` | この時間帯はおやすみ顔 |
| `pets_per_day` 〜 `neglect_decay` | | なつき度の調整つまみ |

サービス定義のタイプ：

```jsonc
{ "name": "my-agent",  "type": "systemd-user", "target": "my-agent.service" }   // systemctl --user
{ "name": "postgres",  "type": "systemd",      "target": "postgresql.service" } // systemctl
{ "name": "my-daemon", "type": "launchd",      "target": "com.example.daemon" } // macOS
{ "name": "ollama",    "type": "process",      "target": "ollama serve" }       // pgrep -f
```

## スマホ / PWA

サーバーは `0.0.0.0` で待ち受けるので、LAN や VPN（Tailscale など）内の
どの端末からも開けます。PWA のフル機能（ホーム画面インストール等）には
HTTPS が必要ですが、Tailscale ならコマンド1発です：

```bash
tailscale serve --bg --https=8444 8090
# -> https://<マシン名>.<tailnet>.ts.net:8444/
```

あとはスマホで「ホーム画面に追加」。

## プライバシーとセキュリティ

- **セッション検知は内容を読みません。** プロセスごとの CPU 時間（`ps`）だけで
  「作業中」か「待ち」かを判定します。
- **使用量枠**は Anthropic の**非公式**エンドポイント（`/usage` コマンドと同じ）
  から取得します。`~/.claude/.credentials.json` の OAuth トークンを
  **読み取り専用**で使い、書き換え・リフレッシュは一切しません。非公式なので
  いつか壊れる可能性はあります。`"claude_usage": false` で無効化できます。
- なつき度は隣の `pet_state.json` に保存。外部送信は一切ありません。
- ポートを localhost の外に公開すると、届く人は誰でもサービス名を見たり
  なでたりできます（最悪でも「勝手になでられてなつき度が上がる」程度・
  1日の上限あり）。LAN/VPN 内に留めるのを推奨します。

## オプション：カメラ人感検知（Raspberry Pi + Sony IMX500）

[Raspberry Pi AI Camera](https://www.raspberrypi.com/products/ai-camera/)
（Sony IMX500）があれば、`watcher.py` が**カメラセンサー内の NPU** で人物検出
を実行し、目が部屋の中のあなたを追いかけます。30分以上の不在後は
「おかえりなさい！」。フレームの保存・送信は一切なく、`{present, count, cx}`
の数値だけを localhost に POST します。

```bash
python3 watcher.py   # picamera2 + IMX500 モデルが必要（Raspberry Pi OS に同梱）
```

カメラがなくてもスマホ版の代替が動きます：3時間ぶりにアプリを開くと
「おかえりなさい」、指スライドで目が追いかける。

## カスタマイズ

- 名前・言語：`config.json`
- セリフ（日英両方）：`index.html` の `I18N`
- 表情：`index.html` の mood ごとの小さな CSS ブロック
- アイコン：`python3 make_icons.py`
- なつき度カーブ：`server.py` の `LEVEL_THRESHOLDS`

## ライセンス

MIT
