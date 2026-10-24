# snow-hokkaido

**北海道に雪がつもっていく様子を、人工衛星の写真から、毎日記録していくプロジェクトです。**
A daily, cloud-aware snow-cover ledger for Hokkaido, built on Sentinel-2 COGs and XYZ-tile cells, aggregated by municipality.

> いまの状態: **試作の途中**です。2026-10-18の衛星写真1回分を、北海道の広い範囲(168市町村)で集計できています。毎日の自動追加と、過去の日付に遡る表示は、まだです。地図のセル表示は、大雪山を含む1タイルだけです。

## まず見てみよう

**公開ページ: https://dwg7.unopengis.org/snow-hokkaido/** (GitHub Pages。`main` の `docs/` を配信しています)。日付ごとの地図ファイルは、Source Cooperative (`smartmaps/foil4gr1/snow-hokkaido/`) から読み込みます。

ブラウザで `docs/index.html` を開く計器盤です(ローカルで見るなら `python3 -m http.server 8765 --directory docs` のあと `http://localhost:8765/`)。左のメニューに計器が並んでいます。

- **地図 (MapLibre)** … 地図の上に、セルごとの色(雪=青、雪でない=緑)を重ねて表示します。「最終既知」(最後に見えた状態と、見えてからの日数)と「観測値」(その日に撮れた場所だけ)を切り替えられ、日付はスライダーで動かせます。海岸・川・道路・行政界の線と地名は、色の上に描かれます。
- **アルゴリズムの説明** … 雪の判定から、セル・市町村への集計、「最終既知」の地図まで、どう作っているかを、文章で説明するページです。
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
just obs 2026-10-18                       # その日(日本時間)の衛星写真から、セルごとの 緑/雪/雲/影 を作る(全域で約20分)
just events ledger/obs/season=2026/2026-10-18/<パスの名前>   # 市町村ごとに数える(パスのフォルダを渡す)
just test                                 # 数え方が矛盾していないか自動で検算する
just docs-data                            # 表示用の軽いデータを作る
```

`just cellmap` には、国土数値情報の「行政区域」データが必要です。**このリポジトリは、市町村の境界データ(とその加工物)を配布しません。** 利用する人が、自分で `just fetch-n03` を実行して取得し、`just cellmap` で組み立ててください(`data/raw/` に置かれ、`.gitignore` で除外されます)。理由は、元になった国土地理院の測量成果の複製・使用に承認が要る可能性があり、そこまでは確認していないためです。

## わかっていないこと・限界 (正直に書きます)

- 1枚の写真でしか動作を確かめていません。雲が多い日の挙動は、まだ見ていません。
- 雪かどうかは、衛星データの SCL (雪 = 分類11) をそのまま使っています。画像との見比べはしましたが、実際の雪との正式な比較 (観測所など) は、まだしていません。
- 衛星データの説明(STAC)に書かれた補正値は、データによっては実際のファイルと合いません。ファイル自身の情報を読むようにして直しましたが、確かめたのは1シーンだけです。
- 市町村の面積を、公式の面積と比べる作業は、まだです(同じポリゴンどうしの照合までしか済んでいません)。
- 地図の表示は、組み込みブラウザ1種類でしか確認していません。
- 常緑針葉樹(冬でも緑の森)や湖の扱いは、まだ入っていません。

詳細な検証メモは [docs/stage1-checks.md](docs/stage1-checks.md) にあります。

## 公開について

このリポジトリは公開されています。個人情報や、大きな生データは入れない方針です(方針は [CLAUDE.md](CLAUDE.md) に書いてあります)。

## データの出典とライセンス

- **コード・文書**: CC0 1.0 ([LICENSE](LICENSE))。
- **データの成果物** (`ledger/`、`docs/data/`、公開先のデータ): CC BY 4.0。下の出典を表記してください。
- **衛星画像**: Contains modified Copernicus Sentinel data 2026 (Sentinel-2 L2A。Copernicus Sentinel データ、ESA。Earth Search (Element 84) の STAC 経由)。
- **市町村境界**: 「国土数値情報(行政区域データ)」(国土交通省)(https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html) をもとに、セルへの割り当てと集計を行って作成しました。国が作成したものではありません。境界データそのものは配布しません。利用する人が `just fetch-n03` で取得してください (国土数値情報の利用条件は CC BY 4.0。元になった国土地理院の測量成果の扱いは、確認していません)。`ledger/grid/cellmap.tif` と `ledger/muni/master.parquet` は、この境界から作った加工物です。
- **背景地図**: bvmap-starlight (国土地理院の最適化ベクトルタイルをもとにしたスタイル、改変者 dwg7/bvmap)。国土地理院コンテンツ利用規約に基づきます。
- **表の地図 (tabular map)**: [tabularmaps/do](https://github.com/tabularmaps/do) の描画部品とデータ (CC0)。`docs/vendor/tabularmap/SOURCE.txt` に取得元のコミットを記録しています。
- **計器盤**: [Open MCT](https://nasa.github.io/openmct/) (NASA)、地図: [MapLibre GL JS](https://maplibre.org/)、PMTiles: [protomaps/PMTiles](https://github.com/protomaps/PMTiles)。
