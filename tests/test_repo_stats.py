"""Offline tests for API semantics, pagination, and failure handling."""

import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import repo_stats as app


def repository(name="demo", **overrides):
    return {
        "full_name": f"matiflp/{name}", "html_url": f"https://github.com/matiflp/{name}",
        "private": False, "fork": False, "has_issues": True, "open_issues_count": 3,
        "stargazers_count": 7, "default_branch": "main", "forks_count": 2, "size": 128,
        "archived": False, "disabled": False, **overrides,
    }


def stats_repository(**overrides):
    return {
        "name": "octocat/demo", "stars": 7, "forks": 2, "watchers": 3,
        "issues_enabled": True, "issues": {"open": 2, "closed": 4, "total": 6}, "open_issues": 2,
        "pull_requests": {"open": 2, "closed": 1, "merged": 5, "draft": 1, "total": 8},
        "default_branch": "main", "fork": False, "archived": False, "disabled": False,
        "language": "Python", "license": "MIT", "size_kb": 128,
        "created_at": "2025-01-01", "updated_at": "2026-11-13", "pushed_at": "2026-11-13",
        "commits": [], "warnings": [], **overrides,
    }


def report_for(repos):
    return {"user": "octocat", "total_stars": sum(repo["stars"] for repo in repos),
            "repositories": repos, "fetched_at": "2026-11-13", **app.summarize_stats(repos)}


def http_error(code, message, headers=None):
    return HTTPError(app.API_URL, code, "error", headers or {}, io.BytesIO(json.dumps({"message": message}).encode()))


class RepositoryStatsTests(unittest.TestCase):
    def test_repository_selection_continues_past_forks_and_pages(self):
        client = app.GitHubClient()
        client.get = Mock(side_effect=[
            ([repository("fork", fork=True)], {"Link": '<https://api.github.com/users/matiflp/repos?page=2>; rel="next"'}),
            ([repository("own"), repository("another")], {}),
        ])
        repos = app.list_repositories(client, "matiflp", 1, False)
        self.assertEqual([r["full_name"] for r in repos], ["matiflp/own"])
        self.assertEqual(client.get.call_count, 2)

    def test_zero_limit_includes_all_selected_repositories(self):
        client = app.GitHubClient()
        client.get = Mock(return_value=([repository("fork", fork=True), repository("own")], {}))
        self.assertEqual(len(app.list_repositories(client, "matiflp", 0, True)), 2)

    def test_star_sort_finds_top_repositories_across_pages_before_limiting(self):
        client = app.GitHubClient()
        client.get = Mock(side_effect=[
            ([repository("recent", stargazers_count=1),
              repository("popular-fork", fork=True, stargazers_count=1000),
              repository("private", private=True, stargazers_count=2000)],
             {"Link": '<https://api.github.com/users/matiflp/repos?page=2>; rel="next"'}),
            ([repository("popular", stargazers_count=50), repository("other", stargazers_count=10)], {}),
        ])
        repos = app.list_repositories(client, "matiflp", 2, False, "stars")
        self.assertEqual([repo["full_name"] for repo in repos], ["matiflp/popular", "matiflp/other"])
        self.assertEqual(client.get.call_count, 2)
        self.assertEqual(client.get.call_args_list[0].args[1]["sort"], "pushed")

    def test_star_sort_zero_limit_includes_forks_and_breaks_ties_by_name(self):
        client = app.GitHubClient()
        client.get = Mock(return_value=([
            repository("Zulu", stargazers_count=5),
            repository("alpha", stargazers_count=5),
            repository("fork", fork=True, stargazers_count=20),
            repository("private", private=True, stargazers_count=100),
        ], {}))
        repos = app.list_repositories(client, "matiflp", 0, True, "stars")
        self.assertEqual([repo["full_name"] for repo in repos], ["matiflp/fork", "matiflp/alpha", "matiflp/Zulu"])

    def test_pushed_sort_stops_at_limit_and_preserves_api_order(self):
        client = app.GitHubClient()
        client.get = Mock(return_value=([
            repository("recent", stargazers_count=0), repository("older", stargazers_count=100),
        ], {"Link": '<https://api.github.com/users/matiflp/repos?page=2>; rel="next"'}))
        repos = app.list_repositories(client, "matiflp", 1, False)
        self.assertEqual([repo["full_name"] for repo in repos], ["matiflp/recent"])
        self.assertEqual(client.get.call_count, 1)

    def test_star_sort_page_failure_does_not_return_a_misleading_top_list(self):
        client = app.GitHubClient()
        client.get = Mock(side_effect=[
            ([repository()], {"Link": '<https://api.github.com/users/matiflp/repos?page=2>; rel="next"'}),
            app.GitHubError("Repository listing unavailable", 503),
        ])
        with self.assertRaisesRegex(app.GitHubError, "listing unavailable"):
            app.list_repositories(client, "matiflp", 1, False, "stars")

    def test_sort_option_reaches_selection_and_json_report(self):
        for options, expected in [([], "pushed"), (["--sort", "stars"], "stars")]:
            output = io.StringIO()
            with self.subTest(sort=expected), patch.object(app, "list_repositories", return_value=[]) as fetch, \
                 contextlib.redirect_stdout(output):
                code = app.main(["-u", "octocat", "--json", *options])
            self.assertEqual(code, 0)
            self.assertEqual(fetch.call_args.args[4], expected)
            self.assertEqual(json.loads(output.getvalue())["sort"], expected)

    def test_issue_count_excludes_pull_requests_on_every_page(self):
        client = app.GitHubClient()
        client.get = Mock(side_effect=[
            ([{"number": 1, "state": "open"}, {"number": 2, "state": "closed", "pull_request": {}}], {
                "Link": '<https://api.github.com/repos/matiflp/demo/issues?page=2>; rel="next"',
            }),
            ([{"number": 3, "state": "open", "pull_request": {}}, {"number": 4, "state": "closed"}], {}),
        ])
        self.assertEqual(app.issue_counts(client, repository()), {"open": 1, "closed": 1, "total": 2})
        self.assertEqual(client.get.call_count, 2)
        self.assertEqual(client.get.call_args_list[0].args[1]["state"], "all")

    def test_disabled_issues_do_not_make_requests(self):
        client = Mock()
        self.assertIsNone(app.issue_counts(client, repository(has_issues=False)))
        client.items.assert_not_called()

    def test_zero_open_issues_does_not_hide_closed_issues(self):
        client = Mock()
        client.items.return_value = [{"state": "closed"}]
        self.assertEqual(app.issue_counts(client, repository(open_issues_count=0)),
                         {"open": 0, "closed": 1, "total": 1})

    def test_pull_request_states_and_drafts_across_pages(self):
        client = app.GitHubClient()
        client.get = Mock(side_effect=[
            ([{"state": "open", "merged_at": None, "draft": True},
              {"state": "closed", "merged_at": "2026-11-13", "draft": False}],
             {"Link": '<https://api.github.com/repos/matiflp/demo/pulls?page=2>; rel="next"'}),
            ([{"state": "closed", "merged_at": None, "draft": True},
              {"state": "open", "merged_at": None, "draft": False}], {}),
        ])
        counts = app.pull_request_counts(client, repository())
        self.assertEqual(counts, {"open": 2, "closed": 1, "merged": 1, "draft": 1, "total": 4})
        self.assertEqual(counts["total"], counts["open"] + counts["closed"] + counts["merged"])
        self.assertEqual(client.get.call_args_list[0].args[1], {"state": "all", "per_page": 100})
        self.assertIn("/pulls", client.get.call_args_list[1].args[0])

    def test_pull_requests_work_with_disabled_issue_tracker(self):
        client = Mock()
        client.items.return_value = [{"state": "open", "merged_at": None, "draft": False}]
        client.get.side_effect = [({"subscribers_count": 2}, {}), ([], {})]
        result = app.collect_stats(client, [repository(has_issues=False)], 1)[0]
        self.assertIsNone(result["issues"])
        self.assertIsNone(result["open_issues"])
        self.assertEqual(result["pull_requests"]["open"], 1)
        self.assertEqual(result["warnings"], [])
        self.assertTrue(client.items.call_args.args[0].endswith("/pulls"))
        self.assertEqual(client.items.call_count, 1)

    def test_watchers_are_subscribers_not_stars(self):
        client = Mock()
        client.get.return_value = ({"subscribers_count": 3, "watchers_count": 70, "stargazers_count": 70}, {})
        self.assertEqual(app.watcher_count(client, repository()), 3)
        client.get.return_value = ({"watchers_count": 70}, {})
        with self.assertRaisesRegex(app.GitHubError, "subscriber count"):
            app.watcher_count(client, repository())

    def test_only_explicitly_empty_repository_is_treated_as_empty(self):
        client = Mock()
        client.get.side_effect = app.GitHubError("Git Repository is empty.", 409)
        self.assertEqual(app.recent_commits(client, repository(), 3), [])
        client.get.side_effect = app.GitHubError("Repository temporarily unavailable.", 409)
        with self.assertRaises(app.GitHubError):
            app.recent_commits(client, repository(), 3)

    def test_commit_does_not_require_a_github_author_account(self):
        client = Mock()
        client.get.return_value = ([{
            "sha": "a" * 40, "html_url": "https://github.com/matiflp/demo/commit/" + "a" * 40,
            "author": None,
            "commit": {"message": "Subject\n\nBody", "author": {"name": "Local author", "date": "2026-11-13T10:00:00Z"}, "committer": None},
        }], {})
        commit = app.recent_commits(client, repository(), 1)[0]
        self.assertEqual(commit["author"], "Local author")
        self.assertEqual(commit["date"], "2026-11-13T10:00:00Z")

    def test_partial_failure_is_not_reported_as_zero_issues(self):
        client = Mock()
        def items(path, params):
            if path.endswith("/issues"):
                raise app.GitHubError("Issues unavailable", 404)
            return []

        client.items.side_effect = items
        client.get.side_effect = [({"subscribers_count": 3}, {}), ([], {})]
        result = app.collect_stats(client, [repository()], 1)[0]
        self.assertIsNone(result["open_issues"])
        self.assertIsNone(result["issues"])
        self.assertEqual(result["pull_requests"]["total"], 0)
        self.assertEqual(result["commits"], [])
        self.assertEqual(len(result["warnings"]), 1)

    def test_failed_pr_page_discards_partial_count_but_keeps_other_stats(self):
        client = app.GitHubClient()
        client.get = Mock(side_effect=[
            ([{"state": "closed"}], {}),
            ([{"state": "open", "merged_at": None}],
             {"Link": '<https://api.github.com/repos/matiflp/demo/pulls?page=2>; rel="next"'}),
            app.GitHubError("Pull requests unavailable", 403),
            ({"subscribers_count": 3}, {}),
            ([], {}),
        ])
        result = app.collect_stats(client, [repository()], 1)[0]
        self.assertIsNone(result["pull_requests"])
        self.assertEqual(result["issues"]["closed"], 1)
        self.assertEqual(result["watchers"], 3)
        self.assertEqual(len(result["warnings"]), 1)
        report = report_for([result])
        self.assertEqual(app.total_label(report, "open_prs"), "0+")
        self.assertEqual(app.total_label(report, "closed_issues"), "1")

    def test_summary_preserves_unknowns_and_avoids_double_counting(self):
        repos = [stats_repository(), stats_repository(
            issues_enabled=False, issues=None, open_issues=None,
            pull_requests=None, watchers=None, archived=True, fork=True,
        )]
        summary = app.summarize_stats(repos)
        totals = summary["totals"]
        self.assertEqual(totals["stars"], 14)
        self.assertEqual(totals["forks"], 4)
        self.assertEqual(totals["watchers"], 3)
        self.assertEqual(totals["total_issues"], 6)
        self.assertEqual(totals["total_prs"], 8)
        self.assertEqual(totals["open_prs"] + totals["closed_prs"] + totals["merged_prs"], 8)
        self.assertEqual(totals["draft_prs"], 1)
        self.assertEqual(totals["archived_repositories"], 1)
        self.assertIn("watchers", summary["incomplete_totals"])
        self.assertIn("total_prs", summary["incomplete_totals"])
        self.assertNotIn("total_issues", summary["incomplete_totals"])

    def test_rate_limit_stops_further_requests(self):
        client = Mock()
        client.items.side_effect = app.GitHubError("rate limit", 429, True)
        with self.assertRaises(app.GitHubError):
            app.collect_stats(client, [repository(), repository("second")], 1)
        client.get.assert_not_called()
        self.assertEqual(client.items.call_count, 1)

    def test_api_headers_and_timeout(self):
        client = app.GitHubClient(token="test-token", timeout=12)
        response = io.BytesIO(b"[]")
        response.headers = {}
        client.opener.open = Mock(return_value=response)
        client.get("/users/matiflp/repos", {"per_page": 100})
        request = client.opener.open.call_args.args[0]
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(headers["authorization"], "Bearer test-token")
        self.assertEqual(headers["x-github-api-version"], app.API_VERSION)
        self.assertIn("repository-stats-cli", headers["user-agent"])
        self.assertEqual(client.opener.open.call_args.kwargs["timeout"], 12)
        self.assertEqual(request.get_method(), "GET")

    def test_http_failures_have_useful_messages(self):
        cases = [
            (401, "Bad credentials", {}, "Invalid token", True),
            (404, "Not Found", {}, "not found", False),
            (403, "API rate limit exceeded", {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1794564000"}, "resets at", True),
            (429, "Too many requests", {"Retry-After": "60"}, "60 seconds", True),
            (403, "Permission denied", {}, "Permission denied", False),
        ]
        for status, message, headers, expected, fatal in cases:
            with self.subTest(status=status, message=message):
                client = app.GitHubClient()
                client.opener.open = Mock(side_effect=http_error(status, message, headers))
                with self.assertRaises(app.GitHubError) as caught:
                    client.get("/users/matiflp/repos")
                self.assertIn(expected, str(caught.exception))
                self.assertEqual(caught.exception.fatal, fatal)

    def test_network_failure_is_not_an_empty_result(self):
        client = app.GitHubClient()
        client.opener.open = Mock(side_effect=URLError("offline"))
        with self.assertRaisesRegex(app.GitHubError, "Network request failed"):
            client.get("/users/matiflp/repos")

    def test_pagination_cannot_forward_token_to_another_host(self):
        client = app.GitHubClient(token="test-token")
        response = io.BytesIO(b"[]")
        response.headers = {"Link": '<https://example.org/collect>; rel="next"'}
        client.opener.open = Mock(return_value=response)
        with self.assertRaisesRegex(app.GitHubError, "outside"):
            list(client.items("/users/matiflp/repos", {}))
        self.assertEqual(client.opener.open.call_count, 1)

    def test_cross_origin_redirect_is_rejected(self):
        with self.assertRaisesRegex(app.GitHubError, "outside"):
            app.GitHubRedirectHandler().redirect_request(None, None, 301, "", {}, "https://example.org/")

    def test_json_output_and_nonzero_exit_for_partial_results(self):
        result = stats_repository(issues=None, open_issues=None, warnings=["issues: HTTP 404"])
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(app, "list_repositories", return_value=[repository()]), \
             patch.object(app, "collect_stats", return_value=[result]), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = app.main(["--username", "matiflp", "--json", "--color", "always"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["total_stars"], 7)
        self.assertEqual(json.loads(stdout.getvalue())["totals"]["merged_prs"], 5)
        self.assertEqual(json.loads(stdout.getvalue())["repositories"][0]["pull_requests"]["open"], 2)
        self.assertIn("open_issues", json.loads(stdout.getvalue())["incomplete_totals"])
        self.assertIn("Warning:", stderr.getvalue())
        self.assertNotIn("\x1b", stdout.getvalue())

    def test_username_is_required_before_any_api_request(self):
        with patch.object(app, "GitHubClient") as client, \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            app.main([])
        self.assertEqual(error.exception.code, 2)
        client.assert_not_called()

    def test_username_aliases_accept_any_account(self):
        for flag in ["--username", "-u", "--user"]:
            with self.subTest(flag=flag):
                self.assertEqual(app.parse_args([flag, "octocat"]).username, "octocat")

    def test_requested_account_is_used_in_api_call_and_report(self):
        output = io.StringIO()
        with patch.object(app, "list_repositories", return_value=[]) as fetch, \
             contextlib.redirect_stdout(output):
            code = app.main(["--username", "octocat", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(fetch.call_args.args[1], "octocat")
        self.assertEqual(json.loads(output.getvalue())["user"], "octocat")

    def test_plain_mode_does_not_require_rich(self):
        output = io.StringIO()
        with patch.object(app, "list_repositories", return_value=[]), \
             patch.object(app, "create_console", side_effect=AssertionError("Rich loaded")), \
             contextlib.redirect_stdout(output):
            code = app.main(["-u", "octocat", "--plain"])
        self.assertEqual(code, 0)
        self.assertIn("octocat", output.getvalue())
        self.assertNotIn("\x1b", output.getvalue())

    def test_invalid_arguments_fail_before_network_access(self):
        for args in [["-u", "octocat", "--limit", "-1"], ["-u", "octocat", "--commits", "0"],
                     ["-u", "octocat", "--commits", "101"], ["--username", "../other"],
                     ["-u", "octocat", "--plain", "--json"], ["-u", "octocat", "--sort", "invalid"]]:
            with self.subTest(args=args), patch.object(app, "GitHubClient") as client, \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                app.main(args)
            self.assertEqual(error.exception.code, 2)
            client.assert_not_called()

    def test_terminal_text_drops_control_characters(self):
        text = app.single_line("hello\x1b[31m\x07\nworld")
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)
        self.assertNotIn("\n", text)

    def test_dashboard_renders_literal_commit_markup_and_missing_data(self):
        from rich.console import Console

        repo = stats_repository(
            issues=None, open_issues=None,
            commits=[{"sha": "a" * 40, "message": "Fix [red]literal[/red] tags\x1b\x07",
                         "author": "Author", "date": "2026-11-13T10:00:00Z"}],
        )
        report = report_for([repo])
        output = io.StringIO()
        console = Console(file=output, width=100, color_system=None, force_terminal=False)
        app.print_dashboard(report, console)
        text = output.getvalue()
        self.assertIn("[red]literal[/red]", text)
        self.assertIn("unavailable", text)
        self.assertIn("Incomplete total", text)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)

    def test_dashboard_fits_narrow_terminal_and_unicode_text(self):
        from rich.cells import cell_len
        from rich.console import Console

        repo = stats_repository(
            name="octocat/a-very-long-repository-name", stars=1000, issues_enabled=False,
            issues=None, open_issues=None, default_branch="feature/a-long-branch", fork=True,
            commits=[{"sha": "b" * 40, "message": "修正表示 — Unicode text that should wrap gracefully",
                         "author": "Author", "date": "2026-11-13T10:00:00Z"}],
        )
        report = report_for([repo])
        output = io.StringIO()
        app.print_dashboard(report, Console(file=output, width=40, color_system=None, force_terminal=False))
        self.assertTrue(all(cell_len(line) <= 40 for line in output.getvalue().splitlines()))
        self.assertIn("disabled", output.getvalue())

    def test_plain_and_dashboard_show_pr_breakdown_and_repository_details(self):
        from rich.console import Console

        report = report_for([stats_repository(archived=True)])
        plain, dashboard = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(plain):
            app.print_table(report)
        app.print_dashboard(report, Console(file=dashboard, width=100, color_system=None))
        for output in (plain, dashboard):
            text = output.getvalue()
            self.assertIn("2 open / 5 merged / 1 closed (unmerged)", text)
            self.assertIn("8 total / 1 drafts (included in open)", text)
            self.assertIn("Watchers: 3", text)
            self.assertIn("License: MIT", text)
            self.assertIn("Status: archived", text)


if __name__ == "__main__":
    unittest.main()
