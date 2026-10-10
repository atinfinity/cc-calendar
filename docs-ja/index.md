---
title: cc-calendar
description: Claude Code のセッションを Google カレンダー風に表示するツール。
---

# cc-calendar { #cc-calendar }

[Claude Code](https://claude.com/claude-code) のセッションを Google カレンダー風に表示します。

`cc-calendar` は、Claude Code が `~/.claude/projects/` に書き出しているトランスクリプトを読み込みます。
いつ、何に取り組み、どれだけのコストがかかり、どんな成果（コミット、変更ファイル、プルリクエスト）が
得られたかを表示します。ローカルの Web UI として動作し、セッションの実行中もライブ更新されます。

[はじめる](getting-started.md){ .md-button .md-button--primary }
[GitHub で見る](https://github.com/atinfinity/cc-calendar){ .md-button }

![プロジェクトごとに色分けされた週のカレンダー](../images/calendar.png)

## 概要 { #at-a-glance }

<div class="grid cards" markdown>

-   **セッションのカレンダー**

    ---

    各セッションは、アクティブだった時間帯に描画されます。日・週・月・年の表示を
    切り替えられます。

    [:octicons-arrow-right-24: カレンダー表示](features.md#calendar-views)

-   **時間とコスト**

    ---

    日ごと・プロジェクトごとのアクティブ時間とコストに加え、キャッシュ効率やツールの使用状況も確認できます。

    [:octicons-arrow-right-24: 時間・コスト・使用量](features.md#time-cost-and-usage)

-   **プロンプトからコミットまで**

    ---

    各リクエストが、その後に続いたコミットとともに、変更ファイル、プルリクエスト、サブエージェントと
    あわせて一覧表示されます。すべてのセッションに完全なトランスクリプトビューアがあります。

    [:octicons-arrow-right-24: セッションの詳細](features.md#sessions-in-detail)

-   **データは手元のマシンに**

    ---

    サーバーは localhost でのみ待ち受け、ログは読み取り専用で読み込みます。唯一のネットワーク
    リクエストは新しいバージョンが出ているかを PyPI に問い合わせるもので、これはオフにできます。
    書き込むのはセッションのメモと、ログから生成してキャッシュする検索インデックスだけです。

    [:octicons-arrow-right-24: プライバシー](privacy.md)

</div>

## クイックスタート { #quick-start }

```sh
uv tool install cc-calendar
cc-calendar
```

インストールせずに試すこともできます: `uvx cc-calendar`。Python 3.12 以降がすでにインストール
されていれば、`pipx install cc-calendar` も使えます。

アップデートは `uv tool upgrade cc-calendar` で行います。[アップデート](getting-started.md#update)を参照してください。

サーバーは空いている localhost のポートでブラウザを開きます。オプションについては
[はじめに](getting-started.md)を参照してください。

!!! note

    このサイトのスクリーンショットは架空のデモデータを表示しています。
