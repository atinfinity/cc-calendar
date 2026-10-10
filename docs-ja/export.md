# エクスポート形式 { #export-format }

リスト表示の **Export** ボタンを押すと、表示中のセッションを CSV または JSON でダウンロードできます。ファイルには
現在のフィルター（検索、プロジェクト、ステータス、"With prompts only"、およびモデル、ブランチ、ソース、評価、タグ、
出力、日付、コストのリストフィルター）を通過したセッションが、現在の並び順で含まれます。

ファイル名は `cc-calendar-sessions-YYYY-MM-DD.csv` または `.json` で、日付はエクスポートした日です。

!!! warning "エクスポートにはセッションデータが含まれます"

    タイトルはプロンプトから、パスはお使いのマシンから取得され、メモも含まれます。
    エクスポートしたファイルはトランスクリプトそのものと同じように扱ってください。

## フィールド { #fields }

CSV と JSON は同じフィールドを同じ順序で持ちます。

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `id` | string | Claude Code のセッション ID |
| `title` | string | セッションのタイトル。Claude Code が生成したタイトル、なければ最初のプロンプトの 1 行目 |
| `project` | string | アプリに表示されるプロジェクト名 |
| `project_path` | string | セッションの作業ディレクトリ |
| `source` | string | セッションを読み込んだ Claude の設定ディレクトリの名前。Source 列と同じです（デフォルトの `~/.claude` なら `local`）。[複数の設定ディレクトリ](getting-started.md#several-config-directories) を参照 |
| `branch` | string or null | ログに記録された Git ブランチ |
| `status` | string | `running`、`waiting`、`done`、`interrupted` のいずれか |
| `rating` | string or null | セッションに付けた評価。`done`、`partial`、`failed` のいずれかで、未評価なら `null`。[メモとタグ](getting-started.md#notes-and-tags) を参照 |
| `start` | string | 最初のアクティビティ。UTC オフセット付きの ISO 8601（例: `2026-09-29T20:15:00+09:00`） |
| `end` | string | 最後のアクティビティ。形式は同上 |
| `active_minutes` | number | アクティブ時間。描画されるバーの長さで、小数点以下 1 桁 |
| `span_minutes` | number or null | `start` から `end` までの分数。アイドル時間を含み、小数点以下 1 桁 |
| `prompts` | integer | 送信したプロンプト数 |
| `tokens` | integer | サブエージェントを含む全トークン数（入力、出力、キャッシュ読み込み、キャッシュ書き込み） |
| `cost_usd` | number | 米ドル建てのコスト。小数点以下 4 桁 |
| `cost_estimated` | boolean | コストがトークン使用量からの推定値のとき `true`（アプリでは `~` 付きで表示） |
| `cache_hit_rate` | number or null | 入力側の全トークン（入力、キャッシュ書き込み、キャッシュ読み込み）に占めるキャッシュ読み込みの割合。0 から 1 |
| `idle_recache_usd` | number | アイドル後にプロンプトキャッシュを書き直す推定コスト。小数点以下 4 桁。[アイドル後の再キャッシュ](features.md#time-cost-and-usage) を参照 |
| `model` | string or null | 最も多くのリクエストで使われたモデル |
| `effort` | string or null | 最も多くのリクエストで使われた effort レベル。`max`、`xhigh`、`high`、`medium`、`low` のいずれか |
| `claude_code_version` | string or null | ログに記録された Claude Code のバージョン（途中で変わった場合は最新のもの） |
| `commits` | integer | セッション中に作成したコミット数 |
| `pull_requests` | integer | セッションが作成した、またはリンクしたプルリクエスト数 |
| `files_changed` | integer | セッションが編集・書き込みしたファイル数 |
| `lines_added` | integer or null | 追加行数。Claude Code のコスト記録から取得します（継続セッションの場合はそのセッション自身の分）。何も書き込まなかった場合や自身の分が不明な場合は `null` |
| `lines_removed` | integer or null | 削除行数。`lines_added` と同様 |
| `cost_per_commit` | number or null | `cost_usd` を `commits` で割った値。小数点以下 4 桁。コミットがなければ `null` |
| `interrupts` | integer | Esc で Claude を止めた回数 |
| `api_errors` | integer | 失敗した API リクエスト数（過負荷、レート制限、接続断など） |
| `queued_prompts` | integer | Claude の作業中に送信し、ターン終了前に読まれたプロンプト数 |
| `tool_calls` | integer | メインセッションのツール呼び出し数。サブエージェントの呼び出しは数えません |
| `tool_errors` | integer | `tool_calls` のうちエラーを返したもの。0 以外で終了したコマンドや、拒否したツール使用を含みます |
| `friction` | integer | `interrupts` + `api_errors` + `queued_prompts` + `tool_errors`。Friction 列と同じです |
| `context_avg` | integer or null | メインスレッドのリクエストあたりの平均コンテキスト（トークン数、入力・キャッシュ書き込み・キャッシュ読み込み）。サブエージェントは含みません。リクエストがなければ `null` |
| `context_peak` | integer or null | 単一リクエストの最大コンテキスト。`context_avg` と同様 |
| `context_bloated` | boolean | 200k トークンを超えて再送したリクエストが 20 件以上あるとき `true`。[コンテキストサイズ](features.md#sessions-in-detail) を参照 |
| `tags` | array of strings | セッションに付けたタグ。表示順で並びます。CSV では `;` で連結します（タグにカンマは使えません）。タグがなければ空。[メモとタグ](getting-started.md#notes-and-tags) を参照 |
| `note` | string | セッションのメモ。なければ空。改行は保持されます |

`active_minutes` は **Split after … idle** 設定に依存します。この設定より長いアイドル時間は
カウントされません。

コストは大まかな目安であり、請求データではありません。[コストについて](features.md#time-cost-and-usage) を参照してください。

## CSV { #csv }

- バイトオーダーマーク付きの UTF-8 で、Excel が非 ASCII のタイトルを正しく読み込めます。改行は CRLF です。
- 1 行目は上記のフィールド名からなるヘッダーです。ほかにメタデータ行はありません。
- カンマ、ダブルクォート、改行を含むフィールドはクォートされ、`"` は二重にされます
  （[RFC 4180](https://www.rfc-editor.org/rfc/rfc4180)）。
- 空のセルは `null` を表します。真偽値は `true` / `false` です。
- `=`、`+`、`-`、`@`、タブ、復帰文字で始まるテキスト値には先頭に `'` が付き、
  スプレッドシートが数式として実行しないようになっています。

## JSON { #json }

JSON はレコードを、形式を識別するオブジェクトで包みます。

```json
{
  "format": "cc-calendar.sessions",
  "schema_version": 1,
  "generator": "cc-calendar 0.7.1",
  "exported_at": "2026-10-04T10:00:00+09:00",
  "sessions": [
    {
      "id": "0b6c1a52-…",
      "title": "Checkout page redesign",
      "project": "acme-web",
      "project_path": "/work/acme-web",
      "source": "local",
      "branch": "main",
      "status": "done",
      "rating": "partial",
      "start": "2026-09-29T20:15:00+09:00",
      "end": "2026-09-29T23:19:00+09:00",
      "active_minutes": 113,
      "span_minutes": 184,
      "prompts": 4,
      "tokens": 6035399,
      "cost_usd": 3.4354,
      "cost_estimated": true,
      "cache_hit_rate": 0.9712,
      "idle_recache_usd": 0.1825,
      "model": "claude-sonnet-5-5",
      "effort": "high",
      "claude_code_version": "2.1.0",
      "commits": 2,
      "pull_requests": 1,
      "files_changed": 6,
      "lines_added": 182,
      "lines_removed": 40,
      "cost_per_commit": 1.7177,
      "interrupts": 1,
      "api_errors": 0,
      "queued_prompts": 2,
      "tool_calls": 84,
      "tool_errors": 5,
      "friction": 8,
      "context_avg": 104512,
      "context_peak": 166830,
      "context_bloated": false,
      "tags": ["redesign", "PR review"],
      "note": "Waiting for design sign-off"
    }
  ]
}
```

| キー | 説明 |
| --- | --- |
| `format` | 常に `cc-calendar.sessions` |
| `schema_version` | 上記フィールド定義のバージョン |
| `generator` | ファイルを書き出した cc-calendar のバージョン（トラブルシューティング用） |
| `exported_at` | ファイルを書き出した日時 |
| `sessions` | レコード。リストの順序で並びます |

数値と真偽値は JSON の型のままです。値がない場合は `null` です。

## プルリクエスト { #pull-requests }

[Pull requests](features.md#time-cost-and-usage) テーブル（ペインとプロジェクトページ）の **Export** ボタンを押すと、
その行を CSV または JSON でダウンロードできます。新しい PR から順に並びます。ファイル名は
`cc-calendar-pull-requests-YYYY-MM-DD.csv` または `.json` です。CSV は上記のルールに従います。

| フィールド | 型 | 説明 |
| --- | --- | --- |
| `url` | string | プルリクエストの Web URL |
| `number` | integer or null | PR 番号 |
| `repository` | string or null | `owner/name` |
| `title` | string or null | `gh pr create` に渡されたタイトル。記録されていない場合（別の方法で PR を作成した場合など）は `null` |
| `head_branch` | string or null | PR の作成元ブランチ |
| `created` | string | PR を作成した日時。UTC オフセット付きの ISO 8601 |
| `opened_in` | string | PR を作成したセッションの ID |
| `sessions` | array | PR に取り組んだセッション。作成したセッションが先頭です。CSV では ID を `;` で連結します。JSON では `id` と `cost_usd`（そのセッションの分）を持つオブジェクトです |
| `active_minutes` | number | 全セッションを通じて PR に費やしたアクティブ時間。小数点以下 1 桁 |
| `requests` | integer | PR のために行った API リクエスト数。サブエージェントを含みます |
| `tokens` | integer | それらのリクエストのトークン数 |
| `cost_usd` | number | それらのリクエストの米ドル建てコスト。小数点以下 4 桁 |
| `cost_estimated` | boolean | コストの一部でもトークン使用量からの推定値であれば `true` |
| `commits` | integer | PR のために作成したコミット数 |

合計値は、表示範囲外のセッションやフィルターで非表示のセッションも含め、PR に取り組んだすべてのセッションを
対象とします。作業を PR に割り当てる方法は [機能](features.md#time-cost-and-usage) で説明しています。
`active_minutes` は **Split after … idle** 設定に依存します。

JSON ファイルは上記と同様に `"format": "cc-calendar.pull_requests"`、`schema_version`、`generator`、
`exported_at` を持ち、レコードは `pull_requests` に、テーブル内のセッションのうちどの PR にも
割り当てられなかった作業は `unattributed` に入ります。

```json
{
  "format": "cc-calendar.pull_requests",
  "schema_version": 1,
  "generator": "cc-calendar 0.7.1",
  "exported_at": "2026-10-04T10:00:00+09:00",
  "pull_requests": [
    {
      "url": "https://github.com/acme/acme-web/pull/42",
      "number": 42,
      "repository": "acme/acme-web",
      "title": "Redesign the checkout page",
      "head_branch": "checkout-redesign",
      "created": "2026-09-29T23:10:00+09:00",
      "opened_in": "0b6c1a52-…",
      "sessions": [
        { "id": "0b6c1a52-…", "cost_usd": 3.1021 },
        { "id": "5d0e77c4-…", "cost_usd": 0.8740 }
      ],
      "active_minutes": 131.5,
      "requests": 212,
      "tokens": 7120944,
      "cost_usd": 3.9761,
      "cost_estimated": true,
      "commits": 3
    }
  ],
  "unattributed": {
    "sessions": 1,
    "active_minutes": 12,
    "requests": 18,
    "tokens": 402311,
    "cost_usd": 0.3333,
    "cost_estimated": true,
    "commits": 0
  }
}
```

## バージョニング { #versioning }

各形式（`cc-calendar.sessions`、`cc-calendar.pull_requests`）はそれぞれ独自の `schema_version` を持ちます。
フィールドの名前変更や削除、意味や単位の変更があったときに上がります。
フィールドの追加では上がらないため、読み込む側は知らないフィールドを無視してください。

CSV にはバージョンフィールドがありません。列は位置ではなくヘッダー名で読み取ってください。

| スキーマバージョン | cc-calendar | 変更内容 |
| --- | --- | --- |
| 1 | 0.3.0 | 最初のバージョン |
| 1 | 0.4.0 | `source`、`tags`、`note` を追加 |
| 1 | 0.6.0 | `pull_requests`、`files_changed`、`lines_added`、`lines_removed`、`cost_per_commit`、`rating`、`idle_recache_usd`、および `interrupts`、`api_errors`、`queued_prompts`、`tool_calls`、`tool_errors`、`friction`、および `context_avg`、`context_peak`、`context_bloated` を追加。プルリクエストのエクスポート（`cc-calendar.pull_requests`、スキーマバージョン 1）を追加 |
