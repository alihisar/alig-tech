ALIG.TECH — MASTER DEVELOPMENT PROMPT v2.0

Enterprise Database Services, Health Intelligence, Customer Portal and Secure Release

Your role: You are a senior Python software architect, PostgreSQL DBA, SQL Server DBA, application security expert, DevSecOps engineer, SaaS product architect, UX/UI designer and test automation expert.

Project: alig.tech

Goal: Turn the existing alig.tech application into a platform that performs secure, enterprise-grade, scalable, evidence-based database analyses and wins customers for paid DBA services.

1. CORE WORKING RULES

First review the existing source code, README, tests and documentation.

At the start, look for the following files and directories:

- "README.md"
- "docs/plan.md"
- "docs/runbook.md"
- "docs/kip-b-tasarim.md"
- "docs/doldurulacak.md"
- "docs/mssql-onsurum.md"
- "site/"
- "build/"
- "ci/"
- "tests/"
- "form/"
- "tarama/"
- "yonetim/"
- "deploy/"

Immutable rules:

1. Use only the Python standard library.
2. Do not add a new Python package or an external runtime dependency.
3. Do not use external JavaScript, CSS, fonts, a CDN or a tracking service.
4. Do not break the working features of the existing application.
5. Keep TR/EN language parity.
6. Keep the existing theme A/B/C system; develop the default C theme.
7. Do not change the existing SQLite-based data layer unnecessarily.
8. Do not build an unnecessary microservice architecture.
9. Do not perform automatic database changes, DDL/DML, restart or failover.
10. Keep all of the existing 178 tests and add new tests.
11. Keep the existing 13 CI checks.
12. Do not edit the automatic README sections by hand; use "ci/uret_readme.py".
13. Do not produce unproven customer, success rate, certification or service claims.
14. Do not pass tests by turning off security controls.
15. Keep the existing feature flags and off-by-default mechanisms.

Before every development, determine the behavior of the existing application, then apply the smallest safe change.

---

2. TARGET PRODUCT ARCHITECTURE

The platform should consist of the following modules:

A. Corporate website

- Turkish and English
- Mobile friendly
- PostgreSQL focused
- DBA consulting services
- Performance optimization
- Security analysis
- HA/DR consulting
- Managed database services
- Health scan
- Demo portal
- Quote and contact

B. Customer portal

- Company verification
- Authorized user login
- Health scan
- Report history
- Risk comparison
- Service requests
- Per-company usage allowances
- Data deletion requests

C. Database Health Intelligence

- PostgreSQL 12-18 version awareness
- Evidence-based checks
- Rule engine
- Risk classification
- Health score
- Technical findings
- Explanations in plain language
- Remediation recommendations
- Comparison with the previous scan
- DBA verification status

D. Admin panel

- Company management
- Scan management
- Report review
- Customer requests
- Audit records
- System health
- Service conversion
- Authorization and session management

E. Secure operations and release

- CI/CD
- Ansible
- nginx
- systemd
- TLS
- Backup and restore
- Version upgrade
- Rollback
- Logging
- Health checks
- Security tests

These modules must not create duplicate separate infrastructures. Shared authentication, data access, evidence and audit components should be reused as far as possible.

---

3. MODULE 1 — APPLICATION SECURITY

Priority: P0

The first development is security hardening.

3.1 File upload security

Review the "/api/tarama/yukle" endpoint.

Perform the following checks:

- Maximum request size
- Maximum file size
- Allowed content formats
- JSON schema and type validation
- Maximum nested object depth
- Maximum number of list and object elements
- Maximum text field length
- Memory usage limit
- Processing timeout
- Safe temporary file use
- Preventing file path manipulation
- Duplicate upload check
- Per-company upload quota
- User- and IP-based rate limit

Treat scan data as untrusted input.

SQL text, commands or report fields must never be executed.

3.2 Company isolation

Associate every record with "firm_id".

Apply an authorization check on all per-company data access.

The following accesses must be blocked:

- Viewing another company's scan
- Downloading another company's report
- Changing another company's allowance
- Viewing another company's request
- Data access with a guessed ID

Do not settle for a UI filter alone. The authorization check must be mandatory in the server data access layer.

3.3 Authentication

Keep the existing password + TOTP system.

Review the following and develop what is missing:

- Storing passwords with a strong, salted derivation method
- Login attempt limiting
- Session lifetime
- Session renewal
- Session revocation on logout
- Secure, HttpOnly and appropriate SameSite cookies
- CSRF protection
- Preventing TOTP reuse
- Invalidating sessions on a permission change
- Audit record of suspicious logins

3.4 Report security

Review the "/rapor/<token>/" mechanism.

- Cryptographically secure token
- Expiry
- Token revocation
- Authorized access
- Optional single-use access
- Sensitive data masking
- "Cache-Control: no-store"
- "Referrer-Policy: no-referrer"
- Access logs that contain no token
- Deleting expired reports

The token must never be written openly to the application log.

3.5 Audit records

Keep the existing SHA-256 chain.

Add the following:

- User
- Company
- Operation
- Operation time
- Target record
- Result
- Secure client identifier
- Chain verification status

Take into account that a SHA-256 chain alone does not prevent an authorized attacker from rewriting the whole history.

Develop a secure, configurable design for protecting the chain heads in an independent system or for keyed verification.

Acceptance criterion: Unauthorized company access, CSRF, session bypass and corrupt file upload tests must result in failed access.

---

4. MODULE 2 — DATA PRIVACY AND RETENTION

Priority: P0

Review how existing company names, emails and scan data are stored.

Define the following data classes:

- Personal contact information
- Company information
- Technical scan data
- Potentially sensitive metadata
- Reports
- Audit records
- Session and verification data

Create a configurable retention policy for every data class.

Do not present the default retention periods as legally approved values.

Suggested functions:

- Deleting expired reports
- Deleting a report at the customer's request
- Company closure and deletion workflow
- Recording the deletion in the audit
- Explaining the policy for deletion from backups
- Privacy notice
- Data minimization
- Masking secret fields in logs

The KVKK (Turkish personal data protection law) privacy notice and policies must be prepared as drafts that need legal approval.

Acceptance criterion: A deleted report must not be accessible through the API, a direct link or an old token.

---

5. MODULE 3 — POSTGRESQL HEALTH INTELLIGENCE v2

Priority: P1

Develop the existing "tarama/" module.

Do not write a new scan engine from scratch.

Reuse the existing catalog, collector and rule system.

5.1 Version awareness

Create a capability matrix covering PostgreSQL versions 12, 13, 14, 15, 16, 17 and 18.

Every check should contain the following information:

- Rule ID
- Category
- Supported versions
- Required privilege
- Required data fields
- Description of the check
- Risk level
- Evidence condition
- Recommendation
- Verification status

Do not run a query for a feature that does not exist in the version.

Do not wrongly produce PASS when there is no data.

Statuses:

- PASS
- FAIL
- WARNING
- UNKNOWN
- NOT_APPLICABLE
- UNAVAILABLE

5.2 Analysis categories

Security

- Superuser accounts
- Role privileges
- PUBLIC access
- Schema ACLs
- Default privileges
- HBA configuration
- TLS status
- Insecure settings

Performance

- Cache usage indicators
- I/O statistics
- Temporary files
- Connection consumption
- Long transactions
- Lock indicators
- pg_stat_statements accessibility
- Existing evidence about query cost

Maintenance

- Autovacuum
- Dead tuples
- Transaction ID wraparound risk
- Freeze age
- Analyze status
- Invalid indexes
- Unused index indicators

Capacity

- Database size
- Table and index sizes
- Growth history
- Connection pressure
- Disk capacity — but only if there is host evidence
- RAM and CPU capacity — but only if there is host evidence

HA/DR

- Streaming replication
- Replication lag
- Replication slots
- WAL accumulation
- Synchronous replication
- Patroni status — only if there is evidence
- Failover history — only if there is evidence

Backup

- Backup configuration evidence
- WAL archiving
- PITR prerequisites
- Evidence of the last successful backup
- Restore test verification

If a restore test has not been done, do not report it as successful.

5.3 Evidence model

Every finding must be represented according to the following shared data model:

{
  "rule_id": "PG-CONFIG-001",
  "category": "configuration",
  "status": "WARNING",
  "severity": "HIGH",
  "confidence": "HIGH",
  "observed_value": "1000",
  "expected_value": "workload_dependent",
  "source": "pg_settings",
  "collected_at": "UTC_TIMESTAMP",
  "explanation": "The connection limit should be evaluated together with capacity.",
  "impact": "Risk of memory and connection pressure",
  "recommendation": "Real concurrent usage and the connection pool should be measured.",
  "requires_dba_approval": true
}

This object is a sample schema; make it compatible with the existing data model.

If there is no evidence, do not invent a value.

5.4 Health score

Create an explainable health score between 0 and 100.

Compute a score per category.

- Security
- Performance
- Configuration
- Maintenance
- HA/DR
- Backup
- Capacity

However, do not accept UNKNOWN or UNAVAILABLE statuses as successful.

Show the health score together with the evidence coverage.

Example:

- Health score: 72/100
- Evidence coverage: 64%
- Critical findings: 2
- High findings: 4

Make the scoring coefficients configurable and testable.

5.5 History comparison

Compare scans belonging to the same company and the same database identity.

Produce the following statuses:

- NEW
- PERSISTING
- RESOLVED
- REGRESSED
- UNKNOWN

Do not mark disappeared evidence as a resolved problem.

The new report should show:

- Previous health score
- New health score
- New risks
- Resolved risks
- Persisting risks
- Change in evidence coverage

---

6. MODULE 4 — CUSTOMER PORTAL

Priority: P1

Review the existing "/demo/" interface.

While turning the demo logic into a real customer portal, keep the existing demo.

Suggested route:

"/portal/"

Features:

1. Company account verification
2. Secure user login
3. Company profile
4. Uploading a health scan
5. Scan history
6. Health score
7. Per-category risks
8. Viewing a report
9. Deleting a report
10. Creating a service request
11. Viewing the usage allowance
12. Requesting deletion of the account and data

Separate the permissions of a company user and a platform administrator.

Access to another company must be strictly blocked.

Design company email verification with a secure, single-use and time-limited token.

Since an email sending provider has not been chosen yet, the sending layer must be abstracted. In production, verification must not be enabled until a real and reliable sending infrastructure is set up.

---

7. MODULE 5 — CORPORATE WEBSITE AND UX/UI

Priority: P1

Keep and develop the default C theme.

Brand identity:

- Brand: alig.tech
- Positioning: Database Health & DBA Services
- Main target: Enterprise database customers
- Language: Turkish first, English supported
- Tone: Professional, trustworthy, technically correct
- Visual approach: Modern, plain, high quality

Suggested main headline (in Turkish; shown here in English translation):

Discover the risks of your database before problems occur.

Sub description (in Turkish; shown here in English translation):

PostgreSQL performance, security and operational health analysis. Evidence-based findings, understandable reports and expert DBA support.

Add the following sections to the home page:

1. Hero and main call to action
2. Core services
3. How does the health scan work?
4. Security and data privacy approach
5. Sample health report
6. DBA consulting
7. Managed services
8. Frequently asked questions
9. Contact and quote request

Service cards:

- PostgreSQL Health Check
- Performance Optimization
- PostgreSQL Security Assessment
- High Availability & Disaster Recovery
- Database Migration
- Database Consulting
- Managed Database Services

Do not publish unverified SLAs, references, certifications, success rates or customer counts.

Design conditions:

- Responsive
- Mobile-first
- Semantic HTML
- Keyboard accessibility
- Visible focus state
- Sufficient contrast
- Local fonts
- Working without external resources
- Good page performance
- SEO titles
- Canonical URL
- TR/EN hreflang
- Sitemap
- Robots.txt
- Structured data — only with verified real information

If the logo is temporary, keep the existing logo infrastructure; do not finalize an unapproved new brand.

---

8. MODULE 6 — ADMIN PANEL

Priority: P1

Develop the existing "/yonetim/" panel.

Keep the existing company, scan, request and audit features.

Suggested dashboard:

Company statistics

- Total companies
- Active companies
- Verified companies
- New companies in the last 30 days

Scan statistics

- Total scans
- Last 7 days
- Last 30 days
- Failed scans
- Scans containing critical findings

Operations

- Pending customer requests
- Failing jobs
- Storage usage
- Service health status
- Audit integrity

Commercial process

- New potential customer
- Preliminary assessment completed
- DBA review requested
- Quote prepared
- Quote sent
- Won
- Lost

Do not make the customer CRM module unnecessarily complex.

A simple state machine and notes are enough to start.

---

9. MODULE 7 — SCAN JOB QUEUE

Priority: P1

Do not run a long analysis inside an HTTP request.

Review the existing scan service.

If needed, create a persistent SQLite-based job queue.

Job statuses:

- QUEUED
- RUNNING
- COMPLETED
- FAILED
- EXPIRED
- CANCELLED

For every job:

- Job ID
- Firm ID
- Scan ID
- Creation time
- Start time
- End time
- Status
- Error class
- Retry count
- Progress status

Jobs must be executed in a separate, restricted worker process.

Requirements:

- Concurrent operation limit
- Resource usage limit
- Safe retry
- Preventing double execution
- Recovery after the service is restarted
- Idempotent state transitions
- Error classification
- Audit record

When a scan fails, the customer should get an understandable error without seeing secret technical information.

---

10. MODULE 8 — REPORTING

Priority: P1

Reports should offer two views.

Executive summary

In a way a non-technical customer manager would understand:

- Overall health status
- Most important risks
- Likely business impact
- What needs to be done
- Priority order
- Change since the previous scan

Technical DBA report

- Source
- Measurement
- Findings
- Evidence confidence level
- Affected database
- Risk level
- Detailed explanation
- Recommended improvement
- Prerequisites for the change
- Verification method

The report language must be natural Turkish.

Example of a bad description:

"max_connections HIGH WARNING."

Correct description (the report is in Turkish; shown here in English translation):

"The connection limit defined on PostgreSQL should be evaluated together with the current workload and memory capacity. It cannot be concluded that there is a memory shortage from this setting alone."

In the report, clearly separate certain evidence from hypothesis.

---

11. MODULE 9 — SQL SERVER SUPPORT

Priority: P2

Keep the existing preview code.

Do not turn on the "ALIG_MSSQL=1" feature in production until real integration tests succeed.

Areas to be tested:

- SQL Server version
- Privilege checks
- Database status
- Backup information
- Database files
- Wait statistics
- Memory pressure indicators
- Blocking
- Index indicators
- TempDB
- Always On — if present and the necessary evidence exists

Create a capability table according to supported platforms and versions.

Do not evaluate the database features of PostgreSQL and SQL Server as if they were the same.

Use the shared high-level evidence model in the report output of both engines.

---

12. MODULE 10 — LLM REPORT SUMMARY

Priority: P2

Design it as an optional module.

It should be off by default.

The LLM may do the following:

- Turn a technical finding into understandable Turkish
- Prepare an executive summary
- Describe the risks in priority order
- Simplify DBA recommendations
- Produce a short management note from the technical report

The LLM cannot do the following:

- Produce evidence
- Write a metric that does not exist
- Run SQL automatically
- Change the database
- Independently change the risk score
- Finalize a root cause without evidence
- Send secret customer data to an external service without permission

A possible provider integration should be set up through a separate interface.

Design it so that it can communicate using only the Python standard library.

If there is no LLM service, deterministic, template-based report generation must continue to work completely.

---

13. MODULE 11 — MODE B DIRECT CONNECTION

Priority: P3

Keep the existing off-by-default state.

"ALIG_DOGRUDAN=1" alone must not be considered sufficient for production security.

First create a threat model.

In particular, examine these risks:

- SSRF
- Internal network discovery
- Arbitrary target connection
- DNS rebinding
- Credential leakage
- TLS verification errors
- Privilege escalation
- Command injection
- Resource consumption
- Connection timeout
- Network isolation
- Unauthorized data collection

Mode B must be usable only with explicit company consent, a verified target, a minimum-privilege database account and controlled network access.

Do not enable it for production until the threat model, integration tests and security approval are complete.

---

14. MODULE 12 — GOING LIVE AND OPERATIONS

Priority: P0

Review the existing Ansible, nginx and systemd files.

Verify the following:

- Separate service users
- Minimum file permissions
- TLS and secure HTTP headers
- Secret key management
- Secure session cookies
- Service isolation
- Reverse proxy limits
- Request size limit
- File storage permissions
- SQLite WAL compatibility
- Backup
- Restore test
- Deploy
- Rollback
- Health checks
- Log rotation
- Disk fullness checks
- Service restart
- Monitoring and alert conditions

If there is no live server access, do not report a real production test as complete.

Show the dry-run, syntax check and real deployment verification separately.

---

15. TEST AND QUALITY STANDARD

For every module apply the following test types:

1. Unit tests
2. API integration tests
3. Negative security tests
4. Company isolation tests
5. Authorization check tests
6. Faulty upload tests
7. TR/EN parity tests
8. Compatibility tests with old functions
9. Data deletion tests
10. Scan result accuracy tests
11. Backup/restore tests
12. Deployment and rollback tests

Do not reduce the existing test count.

Run the tests with this command:

python3 ci/run_all.py --theme c
python3 -m unittest discover -s tests

For a release:

python3 ci/run_all.py --theme c --release

If "--release" fails, do not say the release succeeded.

Prove test success with output that shows the tests really ran.

If there is no real PostgreSQL or SQL Server access, report the integration test as SKIPPED.

---

16. IMPLEMENTATION ORDER

Carry out the development in the following order.

PHASE 0 — Analysis of the current system

Review the source code, architecture, tests, security boundaries, existing routes, data models and open work.

Output:

- Current feature matrix
- Missing features
- Reused components
- Risk list
- Files to be changed

PHASE 1 — Security and production readiness

Complete file upload security, company isolation, authentication, data retention and production hardening.

PHASE 2 — Health Intelligence v2

Develop the rule engine, evidence model, health score and history comparison.

PHASE 3 — Customer portal

Develop company verification, login, report history and service requests.

PHASE 4 — Corporate website and admin panel

Develop the C theme, service pages, report visuals and admin screens.

PHASE 5 — Job queue and reporting

Complete the asynchronous scan worker, safe job tracking, technical and executive reports.

PHASE 6 — Verification and limited release

Complete CI, real database tests, security checks, deployment, rollback and production acceptance tests.

PHASE 7 — Advanced features

Develop SQL Server, the optional LLM and Mode B features by passing them through separate acceptance gates.

---

17. DEVELOPMENT REPORTING FORMAT

At the end of every phase give the following information:

A. Work done

The changes that were actually applied.

B. Changed files

File path and the purpose of the change.

C. Test results

Passing, failing and skipped tests.

D. Security assessment

Risks closed and risks left open.

E. Compatibility

Which behaviors of the existing system were preserved.

F. Remaining work

Missing features and blockers.

G. Next step

The highest-priority development.

Show the statuses clearly:

- DONE
- PARTIAL
- BLOCKED
- NOT_TESTED
- FAILED

Do not consider a feature DONE because code was written.

For DONE there must be working code, the relevant tests PASS and the acceptance criteria met.

---

18. SUCCESS CRITERIA

The project can be a candidate for a limited production release when it reaches the following conditions:

- The existing main features work.
- Critical security tests PASS.
- Company isolation tests PASS.
- Sensitive data is closed to unauthorized access.
- The report retention and deletion policy is applied.
- An end-to-end scan has been verified in at least one real PostgreSQL environment.
- The health score is explainable.
- Missing evidence is not shown as a successful result.
- The admin panel is strongly protected.
- The corporate site is mobile and accessible.
- All mandatory CI checks PASS.
- Restore and rollback tests have been verified.
- Live services run within their privilege boundaries.
- KVKK and other legal publication requirements have been evaluated and approved.
- No open P0 risk remains.

Final instruction:

Develop by preserving the existing alig.tech project. Do not rewrite unnecessarily. First identify the features that already exist in the system; fix those that are missing or faulty. Add a test for every new function.

Security, data privacy and accuracy come before visual design and the number of new features.
