# はじめに { #getting-started }

## インストール { #install }

推奨は [uv](https://docs.astral.sh/uv/) です。必要に応じて Python 3.12 以降を自動で取得します。
pipx や pip も使えます。

=== "ツールとしてインストール"

    ```sh
    uv tool install cc-calendar
    cc-calendar
    ```

    新しいバージョンの入手方法は[アップデート](#update)を参照してください。

=== "インストールせずに実行"

    ```sh
    uvx cc-calendar
    ```

=== "pipx または pip"

    これらには Python 3.12 以降がインストール済みである必要があります。

    ```sh
    pipx install cc-calendar
    cc-calendar
    ```

    pipx を使わない場合は、pip で仮想環境に
    インストールします:

    ```sh
    python3 -m venv .venv
    .venv/bin/pip install cc-calendar
    .venv/bin/cc-calendar
    ```

=== "チェックアウトから実行"

    ```sh
    git clone https://github.com/atinfinity/cc-calendar
    cd cc-calendar
    uv run cc-calendar
    ```

サーバーは `127.0.0.1` の空いているポートで待ち受け、ブラウザを開きます。`~/.claude/projects/` 以下の
ログを読み込むため、Claude Code で実行したセッションはすぐに表示されます。

Linux、macOS、Windows に対応しています。Windows ではログを `%USERPROFILE%\.claude\projects\` から
読み込みます。制限が 1 つあります: **Copy resume command** は 2 つのコマンドを `&&` でつなぎます。
これは cmd と PowerShell 7 では使えますが、Windows PowerShell 5.1 では使えません。その場合は
`&&` を `;` に置き換えてください。

## アップデート { #update }

使用中のバージョンは `cc-calendar --version` で確認できます。各バージョンの変更点は
[リリース](https://github.com/atinfinity/cc-calendar/releases)に記載されています。新しいバージョンが出ると、
トップバーのバージョンの横にこのページへのリンク付きで **vX.Y.Z available** と表示され、ターミナルにも
その旨が出力されます。cc-calendar は起動時と 1 日 1 回 PyPI を確認します。`--no-update-check` で
オフにできます。

=== "uv tool でインストールした場合"

    ```sh
    uv tool upgrade cc-calendar
    ```

    インストール済みのバージョンは `uv tool list` で確認できます。特定のバージョンをインストールする
    （または戻す）には `uv tool install cc-calendar==0.6.0` を使います。

    v0.3.0 以前を GitHub からインストールした場合は、一度だけ `uv tool install --force cc-calendar` で
    PyPI のパッケージに切り替えてください。以降は `uv tool upgrade` が使えます。

=== "uvx で実行している場合"

    `uvx cc-calendar` は最初にキャッシュしたバージョンを再利用します。最新版を指定するには:

    ```sh
    uvx cc-calendar@latest
    ```

=== "pipx または pip"

    ```sh
    pipx upgrade cc-calendar
    ```

    仮想環境の場合: `.venv/bin/pip install --upgrade cc-calendar`。

=== "チェックアウトから"

    ```sh
    git pull
    uv run cc-calendar
    ```

実行中の `cc-calendar` は古いバージョンのまま動き続けます。++ctrl+c++ で停止してから、もう一度
起動してください。実行中のバージョンはトップバーのロゴの横に表示されます。メモ、タグ、評価、検索インデックスは
インストール先の外に保存されるため、そのまま引き継がれます。

## オプション { #options }

| オプション | 説明 |
| --- | --- |
| `--port N` | 空いているポートではなく、指定したポートで待ち受けます |
| `--no-browser` | ブラウザウィンドウを開きません |
| `--claude-dir [NAME=]PATH` | 別の Claude Code 設定ディレクトリからログを読み込みます（デフォルトは `~/.claude`）。複数回指定すると、複数のディレクトリを 1 つのカレンダーに表示します |
| `--notes PATH` | セッションのメモとタグを保存するファイル（デフォルトは[メモとタグ](#notes-and-tags)を参照） |
| `--search-index PATH` | 全文検索インデックスを保存するファイル（デフォルトは[全文検索](features.md#full-text-search)を参照） |
| `--no-update-check` | 新しいバージョンが出ているかを PyPI に問い合わせません。`CC_CALENDAR_NO_UPDATE_CHECK=1` を設定しても同じです。[プライバシー](privacy.md)を参照してください |
| `--version` | バージョンを表示して終了します |

## 複数の設定ディレクトリ { #several-config-directories }

`--claude-dir` を複数回指定すると、複数の場所のセッションをまとめて表示できます。たとえば、他のマシンから
同期した `~/.claude` ディレクトリや、`CLAUDE_CONFIG_DIR` で使い分けている別々の設定などです。読み込まれるのは
指定したディレクトリだけなので、ローカルのセッションも表示するには `~/.claude` を含めてください:

```sh
cc-calendar --claude-dir ~/.claude --claude-dir ~/sync/laptop/.claude --claude-dir work=~/.claude-work
```

各ディレクトリには名前が付きます。`NAME=` で指定した名前、指定がなければ `~/.claude` は `local`、
`.claude` で終わるパスはその親フォルダ名（上の例では `laptop`）、それ以外はフォルダ名そのものです。
セッションの取得元は、一覧（**Source** 列とフィルター）、詳細ペイン、カレンダーのツールチップ、
CSV/JSON エクスポート（`source`）に表示され、**Color by → Source** でディレクトリごとに色分けできます。
複数のディレクトリで見つかったセッションは、最新のアクティビティを含むコピーから 1 つだけ表示されます。

## 基本的な操作 { #finding-your-way-around }

- 上部の **Calendar / List** で、カレンダーと並べ替え可能なセッションの表を切り替えます。
- **Day / Week / Month / Year** で表示期間を選びます。◀ ▶ で移動し、**This week**（期間に応じて **Today**、**This month**、**This year**）で
  現在に戻ります。
- 検索ボックス、プロジェクトフィルター、ステータスチップで、すべての表示を絞り込めます。**With
  prompts only**（デフォルトでオン）は、プロンプトが送信されなかったセッションを非表示にします。合計やレポートも
  これらのフィルターに従います。**Full text** にチェックを入れると、タイトルとプロンプトだけでなく
  トランスクリプト全体を検索します。[全文検索](features.md#full-text-search)を参照してください。
- セッションをクリックすると詳細ペインが開きます。詳細ペインからトランスクリプトを開けます。
- **Summary**、**Tools**、**Copy report** は表示中の範囲を対象にします。
- `?` を押すとキーボードショートカットが表示されます: `←` `→` で移動、`j` `k` でセッションを順に移動、`Enter`
  でトランスクリプトを開き、`Esc` で閉じます。[キーボードショートカット](features.md#keyboard-shortcuts)を参照してください。

## メモとタグ { #notes-and-tags }

セッションに付けたメモ、タグ、評価は、セッション ID をキーとして 1 つの JSON ファイルに保存されます:

| プラットフォーム | デフォルトの場所 |
| --- | --- |
| macOS | `~/Library/Application Support/cc-calendar/notes.json` |
| Linux | `$XDG_DATA_HOME/cc-calendar/notes.json`（未設定の場合は `~/.local/share/…`） |
| Windows | `%APPDATA%\cc-calendar\notes.json` |

別の場所に保存するには `--notes` で別のファイルを指定します。たとえば同期フォルダを指定すれば、マシン間で
メモを共有できます。他の場所でファイルに加えられた変更も反映されます。1 つのファイルがすべての
`--claude-dir` で共有されます。Claude Code がセッションの古いログを削除しても、メモはファイルに残ります。
