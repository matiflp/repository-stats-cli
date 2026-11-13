# Repository Stats CLI

A Python CLI that uses the **GitHub REST API** to display any user's public
repository stars, forks, watchers, issues, pull requests, and recent commits in a
colorful terminal dashboard, with totals and details for each repository.

**Maintainer:** [@matiflp](https://github.com/matiflp)  
**Support:** [matias.lopez.artes@gmail.com](mailto:matias.lopez.artes@gmail.com)

## Quick start

Requires **Python 3.10 or newer**. The dashboard uses
[Rich](https://github.com/Textualize/rich); API requests use Python's standard library.

```bash
cd ~/source/repos/repository-stats-cli
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python repo_stats.py --username matiflp
```

**`--username` is required:** choose any GitHub username. There is no default
account. `-u` and `--user` are aliases; `matiflp` is the project maintainer and just
an example account to query.

By default, it shows the selected user's five most recently pushed public
repositories, excluding forks, with up to three recent commits per repository.

```bash
# Choose any user and the amount of detail
python repo_stats.py --username matiflp --limit 2 --commits 2

# Short username option
python repo_stats.py -u matiflp

# Show the five public repositories with the most stars
python repo_stats.py --username matiflp --sort stars --limit 5

# Include forks and all public repositories owned by the user
python repo_stats.py --username matiflp --limit 0 --include-forks

# JSON for scripts or other tools
python repo_stats.py --username matiflp --limit 2 --json > stats.json

# Plain text or a dashboard without colors
python repo_stats.py --username matiflp --plain
python repo_stats.py --username matiflp --color never

# Full usage
python repo_stats.py --help
```

### Repository ordering

- **`--sort pushed` (default):** latest push first, in GitHub's returned order.
- **`--sort stars`:** most stars first; ties are ordered by full repository name
  alphabetically, ignoring case. All eligible public repositories are considered,
  including those on later API pages, before `--limit` is applied.
- Forks are excluded unless `--include-forks` is set. `--limit 0` keeps every
  eligible repository in the requested order. Dashboard, plain text, and JSON
  use the same selection and order.

GitHub's user-repository endpoint does not support sorting by stars, so that mode
fetches every repository-list page before sorting locally. Detailed issue, PR,
watcher, and commit requests are only made for the selected repositories.

### Example output (illustrative excerpt)

```text
╭──────────────────────────────────────────────────────────────────────────────╮
│                                                                              │
│  REPOSITORY STATS                                                            │
│  @octocat  /  public repositories                                            │
│                                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
╭───────────────╮    ╭───────────────╮    ╭───────────────╮   ╭───────────────╮
│ 1             │    │ 7             │    │ 2             │   │ 3             │
│ REPOSITORIES  │    │ STARS         │    │ FORKS         │   │ WATCHERS      │
╰───────────────╯    ╰───────────────╯    ╰───────────────╯   ╰───────────────╯
╭───────────────╮    ╭───────────────╮    ╭───────────────╮   ╭───────────────╮
│ 2             │    │ 2             │    │ 5             │   │ 1             │
│ OPEN ISSUES   │    │ OPEN PRS      │    │ MERGED PRS    │   │ COMMITS SHOWN │
╰───────────────╯    ╰───────────────╯    ╰───────────────╯   ╰───────────────╯
Totals cover the selected repositories only. Issues exclude pull requests.
╭────────────────────────────── ACTIVITY TOTALS ────────────────────────────────╮
│ Issues: 2 open / 4 closed / 6 total                                           │
│ PRs: 2 open / 5 merged / 1 closed (unmerged)                                   │
│      8 total / 1 drafts (included in open)                                    │
│ Repository flags: 0 archived / 0 disabled / 0 forks                           │
╰──────────────────────────────────────────────────────────────────────────────╯

  REPOSITORY                                          STARS     ISSUES     PRS
 ──────────────────────────────────────────────────────────────────────────────
  octocat/demo                                            7          2       2
ISSUES and PRS columns show open items.
```

The example repository and numbers are illustrative, not claims about a live
repository. Real values are fetched when you run the CLI. Repository panels below
the table include the issue/PR breakdown, language, license, size, status, dates,
and recent commits with author, SHA, and branch.

### Output modes

- **Dashboard (default):** eight metric cards, activity totals, a repository table,
  detail/commit panels, and a fetching spinner in interactive terminals. The layout
  adapts to terminal width; wide tables also show forks, watchers, and branches.
- **`--color auto|always|never`:** automatic terminal detection by default. Use
  `always` to force ANSI colors or `never` for a dashboard without escape codes.
  Rich respects `NO_COLOR`. Redirected output has no colors in `auto` mode.
- **`--plain`:** a simple text table, without Rich or colors.
- **`--json`:** machine-readable output, without Rich, colors, or a spinner.

`--plain` and `--json` are mutually exclusive and ignore `--color`. Both work with
Python's standard library alone, without installing `requirements.txt`:

```bash
python3 repo_stats.py --username matiflp --plain
```

## What is counted

- **Stars:** `stargazers_count` from the repository response.
- **Forks:** `forks_count`, the number of forks of each selected repository.
  This is distinct from the "forks" repository flag, which counts selected
  repositories that are themselves forks (included with `--include-forks`).
- **Watchers:** actual watching subscribers from `subscribers_count` on the
  repository detail endpoint. GitHub's `watchers_count` is an alias for stars and
  is deliberately not used here. Summed watchers are subscriptions across repos,
  not unique people.
- **Issues:** open, closed, and total issues, **excluding pull requests**, across
  every page of `/issues?state=all`. Even a repository with zero open issues can
  have closed issues, so its history is still fetched. Disabled trackers are
  excluded from issue totals.
- **Pull requests:** all pages of `/pulls?state=all`, classified as **open**,
  **merged** (`merged_at` is set), or **closed without merging**. Thus
  `total = open + merged + closed`. **Drafts** count only open draft PRs and are
  already included in open, not added again. These are PRs targeting each selected
  repository, regardless of author; they are fetched even if issues are disabled.
- **Repository details:** primary language, SPDX license identifier, GitHub's
  reported repository size in KB, archived/disabled/fork flags, and creation,
  update, and last-push dates. Missing language or license is shown as
  `not detected`; `NOASSERTION` means GitHub did not identify an SPDX license.
- **Recent commits:** up to `--commits` entries from each repository's **default
  branch**, in the order returned by GitHub. These are repository commits, not
  necessarily commits authored by the requested user. Displayed dates use the
  Git committer date, falling back to the author date.
- **Totals:** dashboard metrics cover only the selected repositories, not
  necessarily the entire account. A `+` marks an incomplete total when a
  contributing count is unavailable. "Commits shown" counts
  the returned commits, not the full repository history.

Disabled issue trackers are shown as `disabled`. Failed requests are shown as
`unavailable`, with a warning, rather than a misleading zero. An explicitly empty
Git repository has no commits. A user with no matching public repositories
produces a successful empty report.

This version intentionally lists **public repositories only**, even when a token
is supplied. Repositories where the user is only a collaborator are not included.
Results are a live view, not an atomic snapshot: repositories can change between
requests.

## Optional authentication and rate limits

Public data works without authentication. GitHub normally allows **60 requests
per hour per IP** without authentication; authenticated personal requests normally
receive **5,000 per hour**, subject to GitHub's primary and secondary limits.

Set `GITHUB_TOKEN`, or `GH_TOKEN` as a fallback, in your shell environment if you
need authenticated requests. Use GitHub's documented token-creation process:

- [Managing personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- For this public-only CLI, a token with public-repository read access is enough;
  do not grant write permissions for this tool. No token is required to try it.
- Tokens are read from the environment. They are not stored by the application,
  accepted as command-line arguments, or included in output.
- A `.env` file is **not** loaded automatically. Git ignores `.env` files, but
  there is no need to create one.

Requests are sequential, use a 15-second per-request timeout, and stop immediately
on rate limiting or invalid authentication. The CLI reports `Retry-After` or the
reset time when available; it does not retry in a tight loop. Large accounts or
repositories with long issue/PR histories need more requests. Start with
`--limit 2`. Each selected repository normally needs one detail request, one
commit request, and all pages of issues and PRs (100 items per page). No history
is silently truncated; a failed page makes that repository's affected count
unavailable. A token is useful when analyzing larger histories.

## API integration

| Endpoint | Purpose |
| --- | --- |
| `GET /users/{username}/repos` | Public owned repositories, stars, and metadata |
| `GET /repos/{owner}/{repo}` | Actual watcher count (`subscribers_count`) |
| `GET /repos/{owner}/{repo}/issues?state=all` | Open and closed issue counts, excluding PRs |
| `GET /repos/{owner}/{repo}/pulls?state=all` | Open, merged, closed-unmerged, draft, and total PR counts |
| `GET /repos/{owner}/{repo}/commits` | Recent commits on the default branch |

Repository, issue, and PR pagination follows GitHub's `Link` response header. Commits
are intentionally limited to the requested number (maximum 100).

Requests include `Accept: application/vnd.github+json`,
`X-GitHub-Api-Version: 2026-03-10`, and an identifying `User-Agent`. This tool only
performs `GET` requests. Pagination and redirects are restricted to
`https://api.github.com`.

### Exit codes and JSON

- `0`: success, including an empty selection.
- `1`: API/network error, rate limit, missing dashboard dependency, or partial
  results with warnings.
- `2`: invalid command-line arguments.
- `130`: interrupted with Ctrl+C.

With `--json`, stdout contains only the report; diagnostics go to stderr. The
report has `user`, `sort`, `fetched_at`, `repository_count`, `total_stars`, `totals`,
`incomplete_totals`, and `repositories`.

- `totals` includes `stars`, `forks`, `watchers`, `open_issues`, `closed_issues`,
  `total_issues`, `open_prs`, `closed_prs`, `merged_prs`, `draft_prs`, `total_prs`,
  `commits_shown`, `fork_repositories`, `archived_repositories`, and
  `disabled_repositories`.
- `incomplete_totals` lists keys whose totals omit unavailable counts. Their
  numeric values are lower bounds, corresponding to the dashboard's `+` marker.
- `sort` records the requested ordering (`pushed` or `stars`). The `repositories`
  array is already ordered and limited accordingly.
- Each repository includes stars, forks, watchers, metadata, `issues_enabled`,
  `issues: {open, closed, total}`, `pull_requests: {open, closed, merged, draft,
  total}`, `commits`, and `warnings`. `open_issues` is retained as an alias of
  `issues.open`. `pull_requests.closed` always means **closed without merging**.
- `issues`, `pull_requests`, `watchers`, or `commits` being `null` means unavailable
  data; `issues_enabled: false` distinguishes a disabled tracker. Zero counts mean
  successful requests with no matching items. Missing language/license/dates also
  use `null` and do not count as fetch failures.

An empty commit list means the API returned no commits or explicitly reported an
empty repository. A fatal error produces no report.

## Tests

```bash
python -m unittest discover -s tests -v
```

Run tests in the virtual environment with dependencies installed. Tests are
offline and use fake responses. They cover pagination, issue/PR classification,
drafts, disabled trackers, real watcher semantics, incomplete totals, empty
repositories, sorting before limiting across pages, partial failures, rate limits,
authentication, token-safe request destinations, username selection, output modes,
and dashboard rendering with Unicode, narrow terminals, and literal markup. The included GitHub Actions
workflow will install dependencies and run them after the repository is published.

## GitHub Developer Program

GitHub lists two membership prerequisites: an API integration in production or
development, and a support email. This project provides a working integration in
development and the support contact above.

See [the preparation notes](docs/developer-program.md) for official links and a
ready-to-use description. Membership requires completing GitHub's registration
process; creating this project does not enroll the maintainer in the program.

## Support and license

Send bug reports and questions to **matias.lopez.artes@gmail.com**. Include the
Python version, operating system, command (without credentials), and error text.

Copyright (c) 2026 matiflp. Distributed under the [MIT License](LICENSE).
