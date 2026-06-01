# 対象デバイス

基板シルク:

```text
tuya-remote-beacon-E-B1SD V1
xiaoma-office
2024/1/27
```

搭載IC:

```text
B1SD-WE2I
2349ENF068
```

基板上に

* 2.4GHz PCBアンテナ
* 水晶発振子
* UART(TX/RX/GND/VCC)パッド

を確認。

---

# BLEであることの確認

nRF52840 + Wireshark でキャプチャ実施。

ボタン押下時のみ大量のアドバタイズパケットが送信される。

観測されたパケット:

```text
ADV_NONCONN_IND
```

接続要求は発生していない。

Advertising Address:

```text
dc:23:51:7d:96:27
```

ボタン押下時にこのアドレスのパケット数が急増し、
数秒後に停止する。

---

# Tuya Beaconであることの確認

Advertising Data内に

```text
16-bit Service UUID: 0xFD50
```

を含む。

Wireshark表示:

```text
Hangzhou Tuya Information Technology Co., Ltd
```

つまり

```text
UUID = 0xFD50
```

を利用した Tuya Beacon デバイスである可能性が極めて高い。

---

# パケット構造

観測された Service Data 例

OFF:

```text
408060000001dca5fe5f2b113f35d9d9c8237900
408080000001dc764132363bc5c2a3e5fd4d6a00
```

ON:

```text
408060000001e07a48b9853e2b704ce23db09500
408080000001e0aebf447741614920400e429200
```

長さはすべて同一。

---

# 確認できている特徴

Service Dataは

```text
408060000001...
```

と

```text
408080000001...
```

の2種類が存在。

毎回ほぼセットで送信される。

共通ヘッダ部分:

```text
40 80 60 00 00 01
40 80 80 00 00 01
```

この部分は固定に見える。

候補:

* プロトコル識別
* バージョン
* フレームタイプ

---

# OFFボタン5回押下で見えた傾向

取得データ例:

```text
408060000001e70a9a673df24863673e8e927a00
408080000001e701232daa381b17ea805a09af00

408060000001e8533cb2348e27932a4458d9bd00
408080000001e8133423b25592a00c0cc6103200

408060000001e98102643d9d4de4340150a5b200
408080000001e9ba1e476885bdeaf18d9e4c9a00

408060000001ea68bec6cb7d923db796df36a200
408080000001ea8f32964c9cdf2bae875f908f00

408060000001eb44b362c7d97ffc4c92a165b100
408080000001eb1784ca38b15e247ec5a7537700
```

---

# 重要な発見

以下部分が単調増加しているように見える。

```text
e70a
e853
e981
ea68
eb44
```

位置:

```text
408060000001 e70a ...
408060000001 e853 ...
408060000001 e981 ...
```

候補:

* シーケンス番号
* フレームカウンタ
* nonce
* 暗号化カウンタ

---

# 現時点の仮説

単純な

```text
ボタンコード = 01
ボタンコード = 02
```

ではない。

理由:

ON/OFFでペイロード全体が大きく変化している。

候補:

```text
[固定ヘッダ]
[カウンタ]
[暗号化ペイロード]
[MIC]
```

のような構造。

Tuya Beaconで一般的な

* AES
* AES-CCM
* 認証タグ付き暗号化

の可能性あり。

---

# ボタン押下時の送信挙動

ONボタン1回で取得したログでは

* 約1.5秒程度
* 1000パケット以上

のADV_NONCONN_INDを送信。

推測:

```text
ボタン押下
↓
同一コマンドを大量リピート
↓
受信成功率向上
↓
スリープ
```

---

# 次回解析で実施予定

取得予定データ:

```text
ON × 5回
OFF × 5回
```

それぞれ

* 約10秒間隔
* Service Dataのみ抽出

解析目的:

### 1. カウンタ領域特定

OFFで見えた

```text
e70a
e853
e981
...
```

相当部分がONでも同様に増加するか確認。

### 2. ボタンコード領域特定

ON系列とOFF系列で

* 固定で変わる箇所
* 毎回変化する箇所

を比較。

### 3. 暗号化有無の判定

同一ボタン連続押下で

* 一部のみ変化
* 全体がランダム変化

を確認。

---

# 現時点で確定と言える事項

✅ BLEデバイス

✅ ADV_NONCONN_IND利用

✅ Tuya UUID 0xFD50利用

✅ ボタン押下時のみ送信

✅ Tuya Beacon系リモコンの可能性が極めて高い

✅ Service Data内に単調増加カウンタらしき値が存在

❓ ボタンコード位置未特定

❓ 暗号化方式未特定

❓ 60系フレームと80系フレームの役割未特定

この状態で「ON×5」「OFF×5」の Service Data 一覧が揃えば、かなり本格的な差分解析に進めるはずです。

---

# ON×5 / OFF×5 差分解析結果

入力ファイル:

```text
src/parse_log/input/OFF5回10秒間隔.txt
src/parse_log/input/ON5回10秒間隔.txt
```

---

## 確定したパケット構造（20バイト）

```text
byte[0]     = 0x40          固定
byte[1]     = 0x80          固定
byte[2]     = 0x60 or 0x80  フレームタイプ（2種類）
byte[3]     = 0x00          固定
byte[4]     = 0x00          固定
byte[5]     = 0x01          固定
byte[6]     = XX            グローバルカウンタ（ボタン押下ごとに +1）
byte[7~18]  = 12バイト      暗号化ペイロード
byte[19]    = 0x00          終端（固定）
```

---

## カウンタはグローバル（ON/OFF非依存）

```text
OFF 1回目: counter = 0xe7 (231)
OFF 2回目: counter = 0xe8 (232)
OFF 3回目: counter = 0xe9 (233)
OFF 4回目: counter = 0xea (234)
OFF 5回目: counter = 0xeb (235)
 ON 1回目: counter = 0xec (236)  ← OFFの直後から連番継続
 ON 2回目: counter = 0xed (237)
 ON 3回目: counter = 0xee (238)
 ON 4回目: counter = 0xef (239)
 ON 5回目: counter = 0xf0 (240)
```

カウンタ自体には ON/OFF の情報は含まれない。

---

## クリーンなペイロード一覧（各押下の最頻値）

### type=0x60

```text
OFF ctr=e7:  0a 9a 67 3d f2 48 63 67 3e 8e 92 7a
OFF ctr=e8:  53 3c b2 34 8e 27 93 2a 44 58 d9 bd
OFF ctr=e9:  81 02 64 3d 9d 4d e4 34 01 50 a5 b2
OFF ctr=ea:  68 be c6 cb 7d 92 3d b7 96 df 36 a2
OFF ctr=eb:  44 b3 62 c7 d9 7f fc 4c 92 a1 65 b1

ON  ctr=ec:  07 75 a5 f8 d3 fb 93 61 3c 54 bc 47
ON  ctr=ed:  6c a3 c7 41 13 55 07 ee 6a 8c e5 3b
ON  ctr=ee:  ba 39 c8 ff b1 f5 9d 13 f9 f1 57 0a
ON  ctr=ef:  1e ed 9f a8 80 fe 91 84 71 7b a3 f5
ON  ctr=f0:  24 64 ff 13 c2 14 3a 87 1a 85 dd 5a
```

### type=0x80

```text
OFF ctr=e7:  01 23 2d aa 38 1b 17 ea 80 5a 09 af
OFF ctr=e8:  13 34 23 b2 55 92 a0 0c 0c c6 10 32
OFF ctr=e9:  ba 1e 47 68 85 bd ea f1 8d 9e 4c 9a
OFF ctr=ea:  8f 32 96 4c 9c df 2b ae 87 5f 90 8f
OFF ctr=eb:  17 84 ca 38 b1 5e 24 7e c5 a7 53 77

ON  ctr=ec:  d9 84 52 46 1c 1f ae 16 ae 0d 4e 47
ON  ctr=ed:  f3 01 94 db 21 c6 ac 2b 73 75 57 e8
ON  ctr=ee:  59 46 2a 39 6d 73 50 1b 48 2c ef 8a
ON  ctr=ef:  3c 55 6f 5c f7 6f 0f f7 96 2b 27 47
ON  ctr=f0:  db 29 1b 4a ba 46 a2 8c f4 fe 17 7f
```

---

## 暗号化の確定

どのバイト位置も、同じボタンを連続押しするたびに完全に異なる値になる。
連続プレス間の XOR もランダムに見える：

```text
e7^e8: 59a6d5097c6ff04d7ad64bc7
e8^e9: d23ed609136a771e45087c0f
ea^eb: 2c0da40ca4edc1fb047e5313
eb^ec: 43c6c73f0a846f2daef5d9f6  ← OFF→ON の境界でも連続性なし
ec^ed: 6bd662b9c0ae948f56d8597c
```

→ 12バイトのペイロードは **AES 暗号化済み**（AES-CTR または AES-CCM と推測）。
ON/OFF の区別はペイロード内の平文に含まれているが、**鍵なしでは解読不可**。

---

## 更新済み確定事項

✅ BLEデバイス

✅ ADV_NONCONN_IND 利用

✅ Tuya UUID 0xFD50 利用

✅ ボタン押下時のみ送信

✅ パケット構造（20バイト）確定

✅ byte[6] = グローバルカウンタ（ボタン種別非依存）

✅ byte[7~18] = AES 暗号化済みペイロード（12バイト）

✅ 60系フレームと80系フレームは毎回ペアで送信、独立した暗号文

❌ ON/OFF のコマンドコードは暗号化されており鍵なしでは特定不可

---

## 次のアクション候補

### 1. リプレイ攻撃テスト（鍵不要・最短）

最後に取得した ON パケット（counter=0xf0）を送信して動作するか確認：

```text
type=60: 408060000001f02464ff13c2143a871a85dd5a00
type=80: 408080000001f0db291b4aba46a28cf4fe177f00
```

受信側がカウンタ検証を行っていなければそのまま動作する。

### 2. UART 経由でAES鍵取得（確実）

基板上の UART パッド（TX/RX/GND/VCC）に接続。
搭載 IC `B1SD-WE2I` に対して 115200bps 等を試す。
デバッグ出力またはフラッシュダンプから local key を取得する。

### 3. Tuya IoT Platform から鍵取得

デバイスを Tuya アプリでプロビジョニング後、
Tuya Developer Portal の `iot.device.secret.get` API で local key を取得する。
