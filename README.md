# snow-hokkaido

**北海道に雪がつもっていく様子を、人工衛星の写真から、毎日記録していくプロジェクトです。**
A daily, cloud-aware snow-cover ledger for Hokkaido, built on Sentinel-2 COGs and XYZ-tile cells, aggregated by municipality.

> いまの状態: **試作の第1段階**です。大雪山を含む約56 km四方(1つのタイル)と、衛星写真1枚(2026-10-18)だけで動いています。北海道全体にはまだ広げていません。

## まず見てみよう

ブラウザで `docs/index.html` を開く計器盤です(ローカルで見るなら `python3 -m http.server 8765 --directory docs` のあと `http://localhost:8765/`)。左のメニューに計器が並んでいます。

- **地図 (MapLibre)** … 地図の上に、雪(青)と雪でない場所(緑)を重ねて表示します。市町村の線をクリックすると、その市町村の雪の割合が出ます。
- **積雪率 / 雲の割合 / 見えた割合 (tabular map)** … 北海道179の市町村を、同じ大きさの四角に並べた「表の地図」です。色の濃さが数字の大きさです。

## このプロジェクトの考え方 (コンセプト)

人工衛星の写真には、**雲が写る日**があります。雲の下は見えません。ふつうの雪の地図は、見えなかったところを黙って省いたり、昨日の値でうめたりしてしまいます。

このプロジェクトは逆に、**「見えなかった」ことも記録に残します**。「雪がなかった」と「雲で見えなかった」は、まったく別の事実だからです。くわしくは次の3つの文書を読んでください。

| 文書 | 内容 |
|---|---|
| [guide/01-concept.md](guide/01-concept.md) | 何をしたいのか、なぜ「見えなかった」を記録するのか |
| [guide/02-technology.md](guide/02-technology.md) | 使っている技術を、ひとつずつやさしく説明 |
| [guide/03-ai.md](guide/03-ai.md) | AI(Claude Code)をどう使ったか。うまくいったことと、まちがえたこと |

## 動かすには

必要なもの: [uv](https://docs.astral.sh/uv/)、[just](https://just.systems/)、GDAL(地理データを読む道具)。

```bash
just cellmap                              # 市町村のラベルを112mの区画(セル)に割り当てる
just obs 2026-10-18                       # 衛星写真から、セルごとの 緑/雪/雲/影 を作る
just events ledger/obs/season=2026/2026-10-18_s2.tif   # 市町村ごとに数える
just test                                 # 数え方が矛盾していないか自動で検算する
just docs-data                            # 表示用の軽いデータを作る
```

`just cellmap` には、国土数値情報の「行政区域」データが必要です(`data/raw/` に置きます。大きいのでリポジトリには入れていません)。

## わかっていないこと・限界 (正直に書きます)

- 1枚の写真でしか動作を確かめていません。雲が多い日の挙動は、まだ見ていません。
- 雪かどうかの判定ルール(NDSI ≧ 0.42)は暫定です。実際の雪の場所と目で見比べる検証は、まだしていません。
- 衛星データの説明(STAC)に書かれた補正値は、データによっては実際のファイルと合いません。ファイル自身の情報を読むようにして直しましたが、確かめたのは1シーンだけです。
- 市町村の面積を、公式の面積と比べる作業は、まだです(同じポリゴンどうしの照合までしか済んでいません)。
- 地図の表示は、組み込みブラウザ1種類でしか確認していません。
- 常緑針葉樹(冬でも緑の森)や湖の扱いは、まだ入っていません。

詳細な検証メモは [docs/stage1-checks.md](docs/stage1-checks.md) にあります。

## 公開について

このリポジトリは公開されています。個人情報や、大きな生データは入れない方針です(方針は [CLAUDE.md](CLAUDE.md) に書いてあります)。

## データの出典とライセンス

- 衛星画像: Sentinel-2(Copernicus / ESA)。Earth Search(Element 84)の STAC 経由。
- 市町村境界: 国土数値情報「行政区域」(国土交通省)。
- 背景地図: bvmap-starlight(国土地理院の最適化ベクトルタイルをもとにしたスタイル)。国土地理院コンテンツ利用規約に基づきます。
- 表の地図 (tabular map): [tabularmaps/do](https://github.com/tabularmaps/do) の描画部品とデータ(CC0)。`docs/vendor/tabularmap/SOURCE.txt` に取得元のコミットを記録しています。
- 計器盤: [Open MCT](https://nasa.github.io/openmct/)(NASA)、地図: [MapLibre GL JS](https://maplibre.org/)。
