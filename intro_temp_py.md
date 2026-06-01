# 環境構築

## Python セットアップ

以下更新すること。

- pyproject.tomlのname

### UVによる環境作成

pyproject.tomlの存在するフォルダ内で以下コマンドを実行することで作成済み環境と同期する

```powershell
uv sync
```

ライブラリ追加も同時に行う場合、後述の証明書エラーの対応が必要になるケースもある

### パッケージ追加

#### シンプルな追加手段

パッケージを追加する場合は以下

```powershell
uv add <パッケージ名>
```

バージョン指定が必要なら以下

```powershell
uv add "<パッケージ名>==<バージョン>"
```

#### 証明書エラーの対応

uvはMozillaの証明書を利用しているため、環境によってはエラーになる場合がある。
対策として`--native-tls`フラグと共にコマンドを実行する。

```powershell
uv add <パッケージ名> --native-tls
```

uv syncでエラーが生じる場合も同様である。

```powershell
uv sync --native-tls
```

#### ローカルパッケージの追加

ローカルのパッケージを直接追加する場合は、`pyproject.toml`に追記する。
追記後、内容を反映するために`uv sync`を実行する。

```text
[project]
dependencies = [
    # 相対パスまたは絶対パスで記述
    "package_name @ file:///path/to/package.whl",
]
```

#### requirementsから追加する場合

requirements.txtから追加するなら以下

```powershell
uv add -r requirements.txt
```

### パッケージ削除

パッケージを除外するなら以下

```powershell
uv remove <パッケージ名>
```
