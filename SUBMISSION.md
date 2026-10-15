# Submission email (to submit@builderr.ai)

Subject: Signalpost Round 1 submission

- Agent name: Signalpost registry-anchored agent
- Repository URL: <fill in after pushing>
- Exact commit hash: <fill in: `git rev-parse HEAD`>
- 100-company smoke-test result: `smoke/out/envelopes.jsonl`, `smoke/out/run-report.json`, `smoke/out/report.html` in the repository
- One-command run instruction (after `python -m venv .venv && .venv/bin/pip install -r requirements.txt`):
  `.venv/bin/python run.py --input <batch.jsonl> --output out`
- Models / APIs / licences: no LLM. Brønnøysund Enhetsregisteret + Regnskapsregisteret open APIs (NLOD 2.0); NAV Arbeidsplassen
  public job-vacancy feed (public token fetched at run time); company-owned websites (robots.txt honoured). Optional Brave Search API
  only if `BRAVE_API_KEY` is set (off by default).
- Expected cost per official run: $0.00 third-party cost; ~870 requests per 100 companies (measured), enforced cap `--max-requests 2000`,
  deadline `--deadline-minutes 42`.
- Contact for results: <name / email>
