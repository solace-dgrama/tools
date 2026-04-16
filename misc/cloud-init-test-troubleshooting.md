# Troubleshooting Cloud-Init Tests

## Overview

Cloud-init tests are **Postman tests**, not standard AFW tests. They live in the
[afw-postman](https://github.com/SolaceDev/afw-postman/tree/main/cloud-init) repo
and run via a dedicated Jenkins job.

Test results appear on the shared dashboard at:
```
https://internal.soltest.net/summary.php?ChildID=<ID>
```

---

## Finding the Logs

### Jenkins Console Output

The primary log source is the Jenkins console. The URL is linked from the dashboard
and follows this pattern:

```
http://192.168.2.82:8080/job/run_postmansuite_VMR/<build_number>/consoleFull
```

### Broker Logs (Graylog)

Broker logs are exported to Graylog. Links to the relevant Graylog queries are
embedded in the dashboard page.

**Credentials** are stored in `labInfo.tcl` under these variables:

```
::LabInfo::GRAYLOG_AUTOMATION_USER
::LabInfo::GRAYLOG_AUTOMATION_PASSWD
```

`labInfo.tcl` lives in a vaulted repo that is symlinked into the `afw2` repo:

```
afw2/afwLib -> /home/automation/git/afw-secrets
```

---

## Converting Graylog Exports to Syslog Format

Graylog lets you export logs as a CSV file. The export has columns:
`timestamp, source, message`, where `message` is a GELF JSON object.

Use `gelf_csv_to_syslog.py` (from [solace-dgrama/tools](https://github.com/solace-dgrama/tools)) to convert it to a readable syslog format:

```bash
gelf_csv_to_syslog.py <exported.csv>
```

Output format per line:
```
<timestamp> <facility.level> <host> appuser: <short_message>
```

Timestamps are converted from UTC to local time. You can pipe the output
into `grep`, `less`, or `afw_log_splitter` for further analysis.
