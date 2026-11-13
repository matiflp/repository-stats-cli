# GitHub Developer Program preparation

Reviewed against the official documentation on **2026-11-13**.

## Published membership prerequisites

[GitHub's Developer Program documentation](https://docs.github.com/en/integrations/concepts/github-developer-program)
states that individual developers and companies can join if they have:

1. An integration **in production or development** using the GitHub API.
2. An email address where GitHub users can contact them for support.

For this project:

| Prerequisite | Project preparation |
| --- | --- |
| Integration using the GitHub API | `repo_stats.py` reads public repository details, issues, pull requests, and commits through the REST API |
| Support email | `matias.lopez.artes@gmail.com`, supplied by the maintainer and documented in the README and CLI help |
| GitHub account for registration | Intended applicant: [`matiflp`](https://github.com/matiflp) |

A public repository, paid plan, OAuth app, GitHub App, Marketplace listing, logo,
or minimum star count is **not listed as a prerequisite on that documentation
page**. Those are not additional requirements invented by this project.

## Registration still to complete

1. Sign in to GitHub as **`matiflp`**.
2. Open [the registration page](https://github.com/developer/register).
3. Supply the integration details and support email requested by the live form.
4. Review and accept any terms personally, including the
   [GitHub Registered Developer Agreement](https://docs.github.com/en/site-policy/github-terms/github-registered-developer-agreement)
   and applicable [GitHub Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service).

The registration form requires authentication; its complete current fields were
not inspected. GitHub controls eligibility and enrollment. These notes record the
published prerequisites, not a guarantee of acceptance or a claim of membership.

The project is currently local and in development. Its intended future repository
is `matiflp/repository-stats-cli`; that repository has **not been created as part of
this preparation**. Supply a public project URL only after it actually exists.

## Suggested integration description

> Repository Stats CLI is a lightweight, read-only command-line integration with
> the GitHub REST API, maintained by matiflp. It retrieves public repository stars,
> forks, watching subscribers, open and closed issues, and pull request counts
> broken down into open, merged, closed-unmerged, and drafts. It also displays
> repository metadata and recent commits from each default branch. Users select the GitHub
> account with --username. It supports a colorful terminal dashboard, paginated
> results, optional token-based authentication, plain text and JSON output, and
> actionable error and rate-limit reporting. The tool runs locally with Python;
> the dashboard uses Rich, while API access uses the standard library.

**Support:** matias.lopez.artes@gmail.com  
**Development status:** working local integration; publication planned.

## Local verification

Verified on 2026-11-13 with Python 3.14.4 and Rich 15.0.0 in a local virtual
environment:

- All 29 offline tests passed, including issue/PR pagination and classification,
  drafts, watchers versus stars, partial totals, username selection, Unicode and
  narrow terminal rendering, and literal commit text containing markup-like text.
- A live, unauthenticated JSON request for `matiflp`, with two repositories and
  one commit each, successfully returned watchers, issue/PR breakdowns, metadata,
  and totals. PR and issue count identities were checked, with no incomplete
  totals, and the resulting dashboard was rendered and inspected.
- Prior live dashboard/color and JSON checks passed; automated tests also confirm
  no ANSI output in JSON even when `--color always` is passed.
- GitHub's `/versions` endpoint confirmed support for `2026-03-10`.

The future CI workflow targets Python 3.10 and 3.14. Hosted CI will be verified
after publication; it has not run locally.

## API behavior

- Reads GitHub data through official REST endpoints; no scraping or write actions.
- Identifies itself via `User-Agent` and requests a supported API version.
- Uses sequential requests, pagination, and explicit request timeouts.
- Reports rate limits and partial failures without pretending missing data is zero.
- Credentials are optional, environment-only, and restricted to GitHub API requests.
- No external analytics, hosted service, or application-managed credential store.

References:

- [REST API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- [REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [REST API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)
- [Developer Program](https://docs.github.com/en/integrations/concepts/github-developer-program)
