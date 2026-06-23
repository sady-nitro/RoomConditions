
# Weather Dashboard Mockup

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
  
