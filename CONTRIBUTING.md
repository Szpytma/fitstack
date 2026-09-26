# Contributing

FitStack is a personal project, published so other people can run it on their
own machine. It is not looking for co-maintainers, and it is not accepting
pull requests.

## Issues are welcome

Open one for a bug, a question about getting it running, or an idea. Please
include your OS, Python and Node versions, and the exact error.

If you hit a problem during setup, check the README first — most of them are
the Garmin token file (`~/.garminconnect/garmin_tokens.json`) being missing or
stale, which the app reports as HTTP 412.

## Pull requests

GitHub lets anyone open a PR against a public repository, but PRs here will be
closed unread. This is not about the quality of the change — it is a
single-user tool with no test suite and no review capacity, and merging
outside code into it would mean taking on maintenance I cannot promise.

Fork it instead. The MIT license means you can take it in any direction you
like, including a fork that does accept contributions.

## Security

Do not open a public issue for anything that looks like a vulnerability. Use
GitHub's private vulnerability reporting on this repository instead.

Note that FitStack handles a Garmin token file, never a Garmin password. If
you find a path where a password could reach the backend, the MCP server, or
any log, that is a bug worth reporting privately.
