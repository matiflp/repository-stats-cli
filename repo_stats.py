#!/usr/bin/env python3
"""Public GitHub repository statistics with an optional Rich terminal dashboard."""

import argparse
import json
import os
import re
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

VERSION = "0.3.0"
API_URL = "https://api.github.com"
API_VERSION = "2026-03-10"
SUPPORT_EMAIL = "matias.lopez.artes@gmail.com"


class GitHubError(Exception):
    """An actionable API error, with enough context to classify failures."""

    def __init__(self, message, status=None, fatal=False):
        super().__init__(message)
        self.status = status
        self.fatal = fatal


def check_api_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise GitHubError("Refusing a request outside https://api.github.com.", fatal=True)


class GitHubRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_api_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GitHubClient:
    def __init__(self, token=None, timeout=15):
        self.timeout = timeout
        self.opener = build_opener(GitHubRedirectHandler())
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": f"repository-stats-cli/{VERSION} (matiflp)",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def get(self, path, params=None):
        url = path if path.startswith("https://") else API_URL + path
        if params:
            url += "?" + urlencode(params)
        check_api_url(url)
        try:
            request = Request(url, headers=self.headers)
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.load(response), response.headers
        except HTTPError as exc:
            try:
                message = json.loads(exc.read()).get("message", exc.reason)
            except (ValueError, AttributeError, UnicodeError):
                message = str(exc.reason)
            headers = exc.headers or {}
            limited = exc.code == 429 or (
                exc.code == 403 and (
                    headers.get("X-RateLimit-Remaining") == "0"
                    or headers.get("Retry-After")
                    or "rate limit" in str(message).lower()
                )
            )
            if limited:
                hint = "Wait before trying again; GITHUB_TOKEN can increase the primary limit."
                if headers.get("Retry-After"):
                    hint = f"Retry-After: {headers['Retry-After']} seconds."
                elif headers.get("X-RateLimit-Reset", "").isdigit():
                    reset = datetime.fromtimestamp(int(headers["X-RateLimit-Reset"]), timezone.utc)
                    hint = f"Primary limit resets at {reset.isoformat()}."
                raise GitHubError(f"GitHub rate limit reached. {hint}", exc.code, True) from None
            if exc.code == 401:
                message = "Invalid token. Check GITHUB_TOKEN/GH_TOKEN or unset it for public access."
            elif exc.code == 404:
                message = "User or repository not found, or this resource is unavailable."
            raise GitHubError(f"HTTP {exc.code}: {message}", exc.code, exc.code == 401) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise GitHubError(f"Network request failed: {exc}. Check connectivity and retry.", fatal=True) from None
        except (ValueError, UnicodeError):
            raise GitHubError("GitHub returned an invalid JSON response.", fatal=True) from None

    def items(self, path, params):
        """Follow every next-page link; never silently truncate activity counts."""
        while path:
            data, headers = self.get(path, params)
            if not isinstance(data, list):
                raise GitHubError("GitHub returned an unexpected list response.", fatal=True)
            yield from data
            match = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("Link", ""))
            path = match.group(1) if match else None
            params = None


def list_repositories(client, username, limit, include_forks, sort="pushed"):
    params = {"type": "owner", "sort": "pushed", "direction": "desc", "per_page": 100}
    selected = []
    for repo in client.items(f"/users/{quote(username, safe='')}/repos", params):
        if repo["private"] or (repo["fork"] and not include_forks):
            continue
        selected.append(repo)
        if sort == "pushed" and limit and len(selected) >= limit:
            break
    if sort == "stars":
        # This endpoint cannot sort by stars. Rank all eligible pages before limiting.
        selected.sort(key=lambda repo: (-repo["stargazers_count"], repo["full_name"].casefold()))
    return selected[:limit] if limit else selected


def issue_counts(client, repo):
    if not repo["has_issues"]:
        return None
    counts = {"open": 0, "closed": 0, "total": 0}
    path = f"/repos/{quote(repo['full_name'], safe='/')}/issues"
    for issue in client.items(path, {"state": "all", "per_page": 100}):
        if "pull_request" not in issue:
            counts[issue["state"]] += 1
            counts["total"] += 1
    return counts


def pull_request_counts(client, repo):
    """Closed means closed without merging; drafts are a subset of open PRs."""
    counts = {"open": 0, "closed": 0, "merged": 0, "draft": 0, "total": 0}
    path = f"/repos/{quote(repo['full_name'], safe='/')}/pulls"
    for pull in client.items(path, {"state": "all", "per_page": 100}):
        if pull["merged_at"] is not None:
            counts["merged"] += 1
        elif pull["state"] == "open":
            counts["open"] += 1
            counts["draft"] += bool(pull.get("draft"))
        else:
            counts["closed"] += 1
        counts["total"] += 1
    return counts


def watcher_count(client, repo):
    # GitHub's watchers_count is an alias for stars, not watching subscribers.
    data, _ = client.get(f"/repos/{quote(repo['full_name'], safe='/')}")
    if not isinstance(data, dict) or not isinstance(data.get("subscribers_count"), int):
        raise GitHubError("GitHub returned no subscriber count.")
    return data["subscribers_count"]


def recent_commits(client, repo, count):
    path = f"/repos/{quote(repo['full_name'], safe='/')}/commits"
    try:
        data, _ = client.get(path, {"per_page": count})
    except GitHubError as exc:
        # Other 409s may mean the repository is temporarily unavailable.
        if exc.status == 409 and "empty" in str(exc).lower():
            return []
        raise
    if not isinstance(data, list):
        raise GitHubError("GitHub returned an unexpected commit response.", fatal=True)
    commits = []
    for entry in data:
        commit = entry["commit"]
        author = commit.get("author") or {}
        committer = commit.get("committer") or {}
        commits.append({
            "sha": entry["sha"],
            "message": commit["message"],
            "author": author.get("name"),
            "date": committer.get("date") or author.get("date"),
            "url": entry["html_url"],
        })
    return commits


def collect_stats(client, repos, commit_count):
    results = []
    for repo in repos:
        result = {
            "name": repo["full_name"],
            "url": repo["html_url"],
            "default_branch": repo["default_branch"],
            "fork": repo["fork"],
            "stars": repo["stargazers_count"],
            "forks": repo["forks_count"],
            "watchers": None,
            "language": repo.get("language"),
            "license": (repo.get("license") or {}).get("spdx_id"),
            "size_kb": repo["size"],
            "archived": repo["archived"],
            "disabled": repo["disabled"],
            "created_at": repo.get("created_at"),
            "updated_at": repo.get("updated_at"),
            "pushed_at": repo.get("pushed_at"),
            "issues_enabled": repo["has_issues"],
            "issues": None,
            "open_issues": None,
            "pull_requests": None,
            "commits": None,
            "warnings": [],
        }
        for field, fetch in (
            ("issues", lambda: issue_counts(client, repo)),
            ("pull_requests", lambda: pull_request_counts(client, repo)),
            ("watchers", lambda: watcher_count(client, repo)),
            ("commits", lambda: recent_commits(client, repo, commit_count)),
        ):
            try:
                result[field] = fetch()
            except GitHubError as exc:
                if exc.fatal:
                    raise
                result["warnings"].append(f"{field}: {exc}")
        if result["issues"] is not None:
            result["open_issues"] = result["issues"]["open"]
        results.append(result)
    return results


def summarize_stats(repos):
    """Totals are lower bounds whenever a contributing request failed."""
    totals, incomplete = {}, []

    def add(key, values):
        totals[key] = sum(value for value in values if value is not None)
        if any(value is None for value in values):
            incomplete.append(key)

    for key in ("stars", "forks", "watchers"):
        add(key, [repo[key] for repo in repos])
    for key in ("open", "closed", "total"):
        add(f"{key}_issues", [repo["issues"][key] if repo["issues"] is not None else None
                             for repo in repos if repo["issues_enabled"]])
    for key in ("open", "closed", "merged", "draft", "total"):
        add(f"{key}_prs", [repo["pull_requests"][key] if repo["pull_requests"] is not None else None
                          for repo in repos])
    totals["commits_shown"] = sum(len(repo["commits"] or []) for repo in repos)
    for key in ("fork", "archived", "disabled"):
        totals[f"{key}_repositories"] = sum(repo[key] for repo in repos)
    return {"totals": totals, "incomplete_totals": incomplete}


def single_line(value):
    """Keep API-controlled text from injecting terminal control sequences."""
    return " ".join("".join(c for c in str(value) if c.isprintable() or c.isspace()).split())


def format_count(value):
    return "unavailable" if value is None else f"{value:,}"


def total_label(report, key):
    suffix = "+" if key in report["incomplete_totals"] else ""
    return f"{report['totals'][key]:,}{suffix}"


def activity_lines(issues, pulls):
    """Accept already formatted counts, shared by the terminal output modes."""
    return [
        f"Issues: {issues['open']} open / {issues['closed']} closed / {issues['total']} total",
        f"PRs: {pulls['open']} open / {pulls['merged']} merged / {pulls['closed']} closed (unmerged)",
        f"     {pulls['total']} total / {pulls['draft']} drafts (included in open)",
    ]


def summary_lines(report):
    issues = {key: total_label(report, f"{key}_issues") for key in ("open", "closed", "total")}
    pulls = {key: total_label(report, f"{key}_prs") for key in ("open", "closed", "merged", "draft", "total")}
    totals = report["totals"]
    return activity_lines(issues, pulls) + [
        f"Repository flags: {totals['archived_repositories']} archived / "
        f"{totals['disabled_repositories']} disabled / {totals['fork_repositories']} forks"
    ]


def repository_detail_lines(repo):
    issues = {key: format_count((repo["issues"] or {}).get(key)) if repo["issues_enabled"] else "disabled"
              for key in ("open", "closed", "total")}
    pulls = {key: format_count((repo["pull_requests"] or {}).get(key))
             for key in ("open", "closed", "merged", "draft", "total")}
    status = ", ".join(key for key in ("archived", "disabled", "fork") if repo[key]) or "active"
    return [
        f"Stars: {repo['stars']:,} / Forks: {repo['forks']:,} / Watchers: {format_count(repo['watchers'])}",
        *activity_lines(issues, pulls),
        f"Language: {repo['language'] or 'not detected'} / License: {repo['license'] or 'not detected'}",
        f"Size: {repo['size_kb']:,} KB / Status: {status}",
        f"Created: {(repo['created_at'] or 'unknown')[:10]} / Updated: {(repo['updated_at'] or 'unknown')[:10]}",
        f"Last push: {(repo['pushed_at'] or 'unknown')[:10]}",
    ]


def sort_description(report):
    labels = {
        "pushed": "latest push first",
        "stars": "most stars first (ties: name A-Z)",
    }
    return f"Sorted by: {labels[report['sort']]}"


def print_table(report):
    repos = report["repositories"]
    print(f"Repository Stats — {report['user']}")
    print(sort_description(report))
    print(f"{len(repos)} public repositories shown; {report['total_stars']} stars across these repositories.\n")
    if not repos:
        print("No public repositories match the selection.")
        return
    print(f"Forks: {total_label(report, 'forks')} / Watchers: {total_label(report, 'watchers')}")
    print("\n".join(summary_lines(report)))
    if report["incomplete_totals"]:
        print("+ Incomplete total; see unavailable counts and warnings.")
    print()
    width = max(len("REPOSITORY"), *(len(single_line(r["name"])) for r in repos))
    print(f"{'REPOSITORY':<{width}}  {'STARS':>7}  {'OPEN ISSUES':>11}  {'OPEN PRS':>11}")
    print(f"{'-' * width}  {'-' * 7}  {'-' * 11}  {'-' * 11}")
    for repo in repos:
        issues = repo["open_issues"]
        if not repo["issues_enabled"]:
            issues = "disabled"
        elif issues is None:
            issues = "unavailable"
        pulls = format_count((repo["pull_requests"] or {}).get("open"))
        print(f"{single_line(repo['name']):<{width}}  {repo['stars']:>7}  {str(issues):>11}  {pulls:>11}")
    print("\nRepository details and recent commits:")
    for repo in repos:
        print(f"\n{single_line(repo['name'])} [{single_line(repo['default_branch'])}]")
        for line in repository_detail_lines(repo):
            print(f"  {single_line(line)}")
        print("  Recent commits (default branch):")
        if repo["commits"] is None:
            print("  Commit data unavailable; see warning.")
        elif not repo["commits"]:
            print("  No commits (empty repository).")
        else:
            for commit in repo["commits"]:
                lines = commit["message"].splitlines()
                subject = single_line(lines[0] if lines else "(no message)")
                print(f"  {commit['sha'][:7]}  {(commit['date'] or 'unknown date')[:10]}  {subject}")


def create_console(color="auto"):
    try:
        from rich.console import Console
    except ImportError:
        raise GitHubError(
            "The dashboard needs Rich. Run: python3 -m pip install -r requirements.txt "
            "(in a virtual environment), or use --plain / --json.", fatal=True,
        ) from None
    return Console(
        force_terminal={"auto": None, "always": True, "never": False}[color],
        color_system=None if color == "never" else "auto",
        markup=False,
        highlight=False,
    )


def print_dashboard(report, console):
    from rich import box
    from rich.columns import Columns
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    repos = report["repositories"]
    heading = Text("REPOSITORY STATS", style="bold bright_cyan")
    heading.append(f"\n@{report['user']}", style="bold")
    heading.append("  /  public repositories", style="dim")
    heading.append(f"\n{sort_description(report)}", style="dim")
    console.print(Panel(heading, border_style="cyan", padding=(1, 2)))

    metrics = [
        (f"{len(repos):,}", "REPOSITORIES", "cyan"),
        (total_label(report, "stars"), "STARS", "yellow"),
        (total_label(report, "forks"), "FORKS", "blue"),
        (total_label(report, "watchers"), "WATCHERS", "cyan"),
        (total_label(report, "open_issues"), "OPEN ISSUES", "green"),
        (total_label(report, "open_prs"), "OPEN PRS", "green"),
        (total_label(report, "merged_prs"), "MERGED PRS", "magenta"),
        (total_label(report, "commits_shown"), "COMMITS SHOWN", "magenta"),
    ]
    cards = [
        Panel(Text.assemble((number + "\n", f"bold {color}"), (label, "dim")),
              border_style=color, padding=(0, 1))
        for number, label, color in metrics
    ]
    console.print(Columns(cards, width=max(18, (console.width - 3) // 4), equal=True, expand=True))
    console.print(Text("Totals cover the selected repositories only. Issues exclude pull requests.", style="dim"))
    if report["incomplete_totals"]:
        console.print(Text("+ Incomplete total; see unavailable counts and warnings.", style="yellow"))
    if not repos:
        console.print(Panel(Text("No public repositories match the selection."), border_style="dim"))
        return

    console.print(Panel(Text("\n".join(summary_lines(report))), title="ACTIVITY TOTALS", border_style="blue"))
    console.print()
    table = Table(box=box.SIMPLE_HEAD, expand=True, header_style="bold", border_style="dim")
    table.add_column("REPOSITORY", ratio=3, overflow="fold")
    show_stars = console.width >= 60
    if show_stars:
        table.add_column("STARS", justify="right", no_wrap=True)
    table.add_column("ISSUES", justify="right", no_wrap=True)
    table.add_column("PRS", justify="right", no_wrap=True)
    wide = console.width >= 100
    if wide:
        table.add_column("FORKS", justify="right", no_wrap=True)
        table.add_column("WATCHERS", justify="right", no_wrap=True)
        table.add_column("BRANCH", ratio=1, overflow="fold")
    for repo in repos:
        name = Text(single_line(repo["name"]), style="bold cyan")
        if repo["fork"]:
            name.append("  fork", style="dim")
        if not repo["issues_enabled"]:
            issues = Text("disabled", style="dim")
        elif repo["open_issues"] is None:
            issues = Text("unavailable", style="red")
        else:
            issues = Text(f"{repo['open_issues']:,}", style="green" if repo["open_issues"] else "dim")
        row = [name]
        if show_stars:
            row.append(Text(f"{repo['stars']:,}", style="yellow" if repo["stars"] else "dim"))
        pulls = (repo["pull_requests"] or {}).get("open")
        row.extend([issues, Text(format_count(pulls), style="red" if pulls is None else "green")])
        if wide:
            row.extend([Text(format_count(repo["forks"])), Text(format_count(repo["watchers"]))])
            row.append(Text(single_line(repo["default_branch"]), style="dim"))
        table.add_row(*row)
    console.print(table)
    console.print(Text("ISSUES and PRS columns show open items.", style="dim"))
    console.print()
    console.rule(Text("REPOSITORY DETAILS", style="bold magenta"), style="dim")
    console.print()
    for repo in repos:
        if repo["commits"] is None:
            body = Text("Commit data unavailable; see warning.", style="red")
        elif not repo["commits"]:
            body = Text("No commits yet — empty repository.", style="dim")
        else:
            body = Table.grid(padding=(0, 1), expand=True)
            body.add_column(width=7, no_wrap=True)
            body.add_column(ratio=1, overflow="fold")
            for commit in repo["commits"]:
                lines = commit["message"].splitlines()
                subject = single_line(lines[0] if lines else "(no message)")
                details = Text(subject, style="bold")
                author = single_line(commit["author"] or "unknown author")
                date = single_line((commit["date"] or "unknown date")[:10])
                details.append(f"\n{date}  ·  {author}\n", style="dim")
                body.add_row(Text(single_line(commit["sha"][:7]), style="yellow"), details)
        console.print(Panel(
            Group(
                Text("\n".join(single_line(line) for line in repository_detail_lines(repo))),
                Text("\nRECENT COMMITS · default branch\n", style="bold magenta"),
                body,
            ),
            title=Text(single_line(repo["name"]), style="bold cyan"),
            subtitle=Text(f"branch: {single_line(repo['default_branch'])}", style="dim"),
            title_align="left", subtitle_align="right", border_style="dim", padding=(1, 2),
        ))
    console.print(Text(f"Fetched {single_line(report['fetched_at'])}  ·  GitHub REST API", style="dim"))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Show public repository stars, forks, watchers, issues, pull requests, and recent commits.",
        epilog=f"Maintainer: matiflp. Support: {SUPPORT_EMAIL}. Optional auth: GITHUB_TOKEN or GH_TOKEN.",
    )
    parser.add_argument("--username", "-u", "--user", required=True,
                        help="GitHub account to query (required; --user is also accepted)")
    parser.add_argument("--sort", choices=("pushed", "stars"), default="pushed",
                        help="order by latest push or most stars, descending (default: pushed)")
    parser.add_argument("--limit", type=int, default=5, help="repositories to show after sorting; 0 = all (default: 5)")
    parser.add_argument("--commits", type=int, default=3, help="recent commits per repository, 1–100 (default: 3)")
    parser.add_argument("--include-forks", action="store_true", help="include forks owned by the user")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    output.add_argument("--plain", action="store_true", help="plain text output without Rich or colors")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                        help="dashboard colors; auto detects terminal support (default: auto)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", args.username):
        parser.error("--username must be a GitHub username (1–39 letters, digits or internal hyphens)")
    if args.limit < 0:
        parser.error("--limit must be 0 or greater")
    if not 1 <= args.commits <= 100:
        parser.error("--commits must be between 1 and 100")
    return args


def main(argv=None):
    args = parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    client = GitHubClient(token=token)
    try:
        console = None if args.json or args.plain else create_console(args.color)
        status = console.status(f"Fetching repositories and activity for @{args.username}...", spinner="dots") if console and console.is_terminal else nullcontext()
        with status:
            repos = list_repositories(client, args.username, args.limit, args.include_forks, args.sort)
            stats = collect_stats(client, repos, args.commits)
    except GitHubError as exc:
        print(f"Error: {single_line(exc)}", file=sys.stderr)
        return 1
    report = {
        "user": args.username,
        "sort": args.sort,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "repository_count": len(stats),
        "total_stars": sum(repo["stars"] for repo in stats),
        **summarize_stats(stats),
        "repositories": stats,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.plain:
        print_table(report)
    else:
        print_dashboard(report, console)
    warnings = [f"{repo['name']}: {warning}" for repo in stats for warning in repo["warnings"]]
    for warning in warnings:
        print(f"Warning: {single_line(warning)}", file=sys.stderr)
    return 1 if warnings else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        sys.exit(130)
    except BrokenPipeError:
        sys.exit(0)
