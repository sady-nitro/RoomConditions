
# Room Conditions Dashboard

React + TypeScriptで実装した室内環境ダッシュボードです。気温・湿度・気圧の現在値、過去24時間の一覧、過去48時間のグラフを表示します。

## 起動方法

```sh
npm install
npm run dev
```

本番ビルドは `npm run build` で作成できます。

## 計測データ

計測値は `public/data/measurements.txt` から読み込みます。空白区切りのUTF-8テキストで、1行目はヘッダーです。

```text
timestamp temperature humidity pressure
2026-06-19T06:00:00+09:00 21.0 71.8 1012.8
```

- `timestamp`: ISO 8601形式
- `temperature`: 気温（°C）
- `humidity`: 湿度（%）
- `pressure`: 気圧（hPa）

## Discord気圧変化アラート

`scripts/pressure_alert.py` は `public/data/data.csv` の直近データから、1・3・6時間変化、回帰傾き、変化加速度を計算します。過去30日間の中央値とMADによるロバストZスコアを使い、通常より大きな変化をDiscord Webhookへ通知します。入力には5列CSVのほか、`measurements.txt`の空白区切り形式も指定できます。

まず、送信せずに判定内容とWebhookペイロードを確認できます。

```sh
python scripts/pressure_alert.py --dry-run
```

別の計測ファイルを使う場合:

```sh
python scripts/pressure_alert.py --data public/data/measurements.txt --dry-run
```

実際に通知する場合はWebhook URLを環境変数へ設定します。

```sh
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
python scripts/pressure_alert.py
```

PowerShellの場合:

```powershell
$env:DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/...'
python scripts/pressure_alert.py
```

同じ方向・同じレベル以下の通知は、デフォルトで6時間抑制されます。主な設定は環境変数で変更できます。

- `PRESSURE_BASELINE_DAYS`: 基準期間の日数（デフォルト: `30`）
- `PRESSURE_COOLDOWN_HOURS`: 再通知を抑制する時間（デフォルト: `6`）
- `PRESSURE_MINIMUM_LEVEL`: 通知する最低レベル（`1`〜`3`）
- `DISCORD_ROLE_ID`: レベル3でメンションするDiscordロールID
- `DISCORD_MENTION_LEVEL`: ロールメンションを開始するレベル
  
### ローカルの `.env` を使う

`.env.example` をリポジトリ直下の `.env` にコピーし、Webhook URLなどを設定してください。

```sh
cp .env.example .env
python scripts/pressure_alert.py
```

`.env` はGitの管理対象外です。OSや実行環境に同名の環境変数が設定されている場合は、その値が `.env` より優先されます。
