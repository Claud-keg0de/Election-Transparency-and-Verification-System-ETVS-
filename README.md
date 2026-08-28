# Election-Transparency-and-Verification-System-ETVS-
An independent, open-source election turnout and results auditing system that verifies published election data without accessing or controlling IEBC's critical infrastructure.

**Background**

I got access to a compromised file on IEBC, signed by then the chairman of IEBC William Chebukati. The pdf file contained information alleging the commission services numerous requests by various entities requiring register of voters for specific electoral areas. These requests are serviced upon payment of certain fees and in accordance with privacy laws requiring personally identifiable information to be kept confidential. That, what was being reported in the media was not data obtained through hacking of the BVR system but possibly from entities that may have legitimately obtained data from the commission through formal request and upon payment of requisite fees.

**Problem Statement**

IEBC has been involved in fraudulent activities regarding past election activities as indicated in the pdf file.

**Proposed Solution**

An integrated open and closed source election transparency verification system.

**Objectives**
1.	Compliance
2.	Transparency
3.	Fraud
4.	Policy

**Election Data Model**

**Polling Station**
1.	Station ID
2.	Station Name
3.	Constituency
4.	Registered Voters
5.	Verified turnout

**Election Result**
1.	Result ID
2.	Station ID
3.	Candidate ID
4.	Votes

**Audit Record**
1.	Audit ID
2.	Station ID
3.	Rule Checked
4.	Status
5.	Timestamp
6.	Previous Hash
7.	Current Hash

**Verification Rules**
1.	Turnout cannot exceed registered voters.
2.	Candidate votes cannot exceed voter ballots.
3.	Account for all ballots.
4.	Constituency totals must match polling stations.
5.	National totals must match lower-level aggregate.
6.	Detect duplicate submissions.
7.	Detect impossible changes.

**System Architecture Diagram**


****ELECTION DATA SOURCE****

Published/Authorized Data (READ ONLY)

****DATA INGESTION API****

Validate Source

Verify Integrity

Sanitize Data

****AUDIT & VERIFICATION ENGINE****

Turnout Checks

Results Checks

Aggregation Checks

Anomaly Detection

****AUDIT LOG****

Tamper - Evident

****PUBLIC DASHBOARD****

Verified Data

Alerts

Statistics


