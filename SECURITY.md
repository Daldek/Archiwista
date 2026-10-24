# Security policy

## Supported versions

Security fixes go into the latest release of Archiwista and into the
development branch `develop`. Older releases are not patched.

## Reporting a vulnerability

Please do not report vulnerabilities in public issues or pull requests.

Use GitHub's private vulnerability reporting: open the **Security** tab of
<https://github.com/Daldek/Archiwista>, choose **Report a vulnerability** and
describe the problem, the affected version and, if possible, how to reproduce
it. You get an answer as soon as the maintainer can read the report; a fix is
released as a patch version and credited in the CHANGELOG unless you prefer
otherwise.

## Scope

Archiwista is a local web server (by default `127.0.0.1` only) that reads the
data stores of Kartograf and, later, IMGWTools and renders previews of files it
finds there. Reports about the session, token and CSRF protection, the
permissions model (roles, groups, project visibility), the handling of paths
and of area files, the isolation of the processes that read and render files,
the local state database, or the supply chain of the package are in scope. The
producers (Kartograf, IMGWTools) and the third-party libraries have their own
policies; report their defects to them.
