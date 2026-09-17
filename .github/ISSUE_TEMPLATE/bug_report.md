---
name: Bug report
about: Create a report to help us improve
title: ''
labels: ''
assignees: ''

---

<!--
BEFORE YOU OPEN A "TimeOut" / "Cannot connect" ISSUE

The component now tells you *why* a device is unreachable. Find the full error
line in your Home Assistant log and read it against the "Reading the failure
message" section of the README. If it says the device REFUSED the request, the
WiFi module does not support local control and there is nothing to fix here.

Issues without the error line and without the hid/ver fields below cannot be
triaged and will be closed.
-->

**Describe the bug**
A clear and concise description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior:
1. Go to '...'
2. Click on '....'
3. Scroll down to '....'
4. See error

**Device**
The WiFi module firmware, not the AC model, decides whether local control works.
These two fields are the single most useful thing you can send. See "What to
include when reporting a connection issue" in the README for how to get them if
the integration does not load.

- hid: <!-- e.g. 362001000748+U-CS532Z(LT)V3.75.bin -->
- ver: <!-- e.g. V1.2.1 -->
- AC brand and model:
- Encryption version (1 or 2):

**Full error line**
For connection problems, paste the complete "All N attempts failed for ..." line.
It names the cause and is what makes the report actionable.

**Configuration**
Share your YAML here

**Expected behavior**
A clear and concise description of what you expected to happen.

**Screenshots**
If applicable, add screenshots to help explain your problem.

**Platform:**
 - OS: [e.g. HASSIO, Hassbian]
 - Browser [e.g. chrome, safari]
 - Version [e.g. 0.92.1]

**Additional context**
Add any other context about the problem here.

**Logs**
Please share your Home Assistant logs here. Make sure to remove any personal/secret information.
