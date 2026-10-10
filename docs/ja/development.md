# 開発 { #development }

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

フロントエンドは `src/cc_calendar/static/` にあるプレーンな HTML、CSS、ES モジュールで、ビルド手順はありません。
テストには合成ログのみを使います。実際のトランスクリプトは決してコミットしないでください。

## スクリーンショット { #screenshots }

スクリーンショットは、`scripts/demo_data.py` が生成する架空のデータ（メモとタグを含む）から描画されます。
インストール済みの Google Chrome を使い、あなた自身のメモや検索インデックスには
手を触れません。

```sh
uv run --with playwright python scripts/screenshots.py
```

## このサイト { #this-site }

このサイトは `docs/` と `zensical.toml` から [Zensical](https://zensical.org/) でビルドしています。
`main` へのプッシュでサイトに関わるファイル（`docs/`、`zensical.toml`、`pyproject.toml`、`uv.lock`）が
変更されると、GitHub Actions が GitHub Pages にデプロイします。

ローカルでプレビューするには次のようにします。

```sh
uv run --group docs zensical serve
```

日本語のページは `docs/ja/` にあり、`zensical.ja.toml` で `site/ja` にビルドされ、`/cc-calendar/ja/` で
公開されます。英語のページを変更したときは、同じプルリクエストで対応する `docs/ja/` のページも更新してください。
見出しの `{ #anchor }` ID は英語のスラッグと同一に保ち、画像は `../images/…` で参照します（どちらも `tests/test_docs.py` で検査します）。
両方のサイトをローカルでビルドするには次のようにします。

```sh
uv run --group docs zensical build --clean
uv run --group docs zensical build -f zensical.ja.toml
```

## リリース { #releasing }

バージョンタグをプッシュすると、`.github/workflows/release.yml` によってパッケージが
[PyPI](https://pypi.org/project/cc-calendar/) に公開されます。

1. `main` でバージョンを上げ（バージョンは `pyproject.toml` にのみ記載されています）、マージします。

    ```sh
    uv version --bump minor   # or --bump patch, or uv version 1.2.3
    ```

2. マージしたコミットにタグを付け、タグをプッシュします。

    ```sh
    git tag v1.2.3
    git push origin v1.2.3
    ```

ワークフローは、タグがバージョンと一致することを確認し、lint とテストを実行し、wheel と sdist をビルドして、
wheel のスモークテストを行います。その後、trusted publishing（`pypi` environment）で PyPI に公開し、
ファイルを GitHub のリリースに添付します。リリースがまだ存在しない場合はドラフトとして作成するので、
リリースノートを書いてから公開できます。

PyPI は同じバージョンを 2 回受け付けません。アップロード後に公開が失敗した場合は、タグを付け直さずに
バージョンをもう一度上げてください。

## 謝辞 { #acknowledgements }

[@tokkyo さんのこちらの投稿](https://x.com/tokkyo/status/2106240136778575897)で紹介されていたツールに着想を得ています。
これは独自に再実装したもので、オリジナルとは関係ありません。
