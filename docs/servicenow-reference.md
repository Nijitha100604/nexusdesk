# ServiceNow Reference (NexusDesk)

Single source of truth for the ServiceNow setup. Contains no passwords or tokens.
Update this file whenever the instance configuration changes.

## 1. Instance

| Item | Value |
|---|---|
| Instance URL | https://devxxxxx.service-now.com |
| Release | Brazil |
| Type | Personal Developer Instance (PDI) |
| Created | 29-10-2026 |
| Last verified | 31-10-2026 |

Keep-alive: log in directly at least every 5 days. A PDI can be reclaimed after
a period without direct logins, and a reclaimed instance loses all data.

## 2. Integration user

| Item | Value |
|---|---|
| User ID | helpdesk_agent_svc |
| Identity type | Machine |
| Web service access only | true (set automatically by Machine) |
| Roles | itil, knowledge |
| Used for | Incident create, read, update; read published knowledge articles |
| Credentials | Stored only in the local .env file (SN_USER, SN_PASSWORD) |

Access boundary (verified as this user):

| Table | Result |
|---|---|
| incident | allowed |
| kb_knowledge (NexusDesk base) | allowed (read) |
| sys_choice, sys_user_group, sys_user | denied (intentional, least privilege) |

Because of this, the agents read choice values and group IDs from the
configuration below instead of querying ServiceNow at runtime.

## 3. Assignment groups

| Group | sys_id | Used for |
|---|---|---|
| Service Desk | xxxxxx | Account and password, other or unknown, fallback |
| Network Support | xxxxxxx | Network and VPN |
| Software Support | xxxxxx | Software and access |
| Hardware Support | xxxxxx | Hardware |
| Messaging Support | xxxxxxx | Email and collaboration |

Note: if any default group was reused, write its real name here.

## 4. Demo callers (synthetic data)

| user_name | Name | Identity type | sys_id |
|---|---|---|---|
| demo.employee1 | Priya Raman | Human | xxxxxx |
| demo.employee2 | Arjun Nair | Human | xxxxxxx |
| demo.employee3 | Meera Krishnan | Human | xxxxxxx |

These users have no roles. They are used only as `caller_id` on tickets.

## 5. Incident field values

The API needs the stored **value**, not the label. Read these as admin
(`sys_choice.list`, Table = incident, Element = field).

### state
| value | label |
|---|---|
| 1 | New |
| 2 | In Progress |
| 3 | On Hold |
| 6 | Resolved |
| 7 | Closed |
| 8 | Canceled |

Typical defaults to compare against: 1 New, 2 In Progress, 3 On Hold,
6 Resolved, 7 Closed, 8 Canceled.

### urgency
| value | label |
|---|---|
| 1 | 1 - High |
| 2 | 2 - Medium |
| 3 | 3 - Low |

### impact
| value | label |
|---|---|
| 1 | 1 - High |
| 2 | 2 - Medium |
| 3 | 3 - Low |

### category
| value | label |
|---|---|
| inquiry | Inquiry / Help |
| software | Software |
| hardware | Hardware |
| network | Network |
| database | Database |

NexusDesk mapping: Network and VPN -> network; Software and Access -> software;
Hardware -> hardware; Email and Collaboration -> software;
Account and Password -> inquiry; Other / Unknown -> inquiry.

### close_code (send the VALUE column)

| value (send this) | label |
|---|---|
| Known error | Known error |
| Duplicate | Duplicate |
| Workaround provided | Resolved – Workaround Applied |
| Resolved by caller | Resolved – Fixed by Caller |
| Resolved – Permanent Fix Applied | Resolved – Permanent Fix Applied |
| Resolved – Fixed by Vendor | Resolved – Fixed by Vendor |
| Resolved – Fixed Without Action | Resolved – Fixed Without Action |
| Resolved - No response from caller | Resolved - No response from caller |
| Not Resolved – Not Reproducible | Not Resolved – Not Reproducible |
| Not Resolved – Problem Raised | Not Resolved – Problem Raised |


Warning: most values use a long dash (en dash), but "Resolved - No response from
caller" appears to use a normal hyphen. Copy values from the instance and do not
retype them. A wrong value causes a 403 "Data Policy Exception: Resolution code".

### NexusDesk close_code mapping

| NexusDesk outcome | close_code value |
|---|---|
| Employee confirms the suggested steps fixed it | Resolved by caller |
| Admin-approved lasting fix | Resolved – Permanent Fix Applied |
| Temporary fix only | Workaround provided |
| Not solved, handed to a human | do not resolve; set assignment_group instead |

Resolving also requires `close_notes`.

## 6. Priority matrix

Priority is calculated by ServiceNow. NexusDesk sets only urgency and impact.
Source: `dl_u_priority.list` (Priority Data Lookup Rules).

| | Urgency 1 | Urgency 2 | Urgency 3 |
|---|---|---|---|
| Impact 1 (High) | 1 - Critical | 2 - High | 3 - Moderate |
| Impact 2 (Medium) | 2 - High | 3 - Moderate | 4 - Low |
| Impact 3 (Low) | 3 - Moderate | 4 - Low | 5 - Planning |

If this differs from the Phase 1 design document, update that document too.

## 7. Knowledge base

| Item | Value |
|---|---|
| Knowledge base name | NexusDesk IT Knowledge (confirm exact name) |
| Knowledge base sys_id | 37109d6c8390571018d5fe55eeaad39d |
| Read access | User criteria "NexusDesk Service Account" (user: helpdesk_agent_svc) |
| Contribute access | admin only (service user is read-only) |
| Demo knowledge bases | Intentionally not readable by the service user |

Sync filter used by the ingestion worker:

```
workflow_state=published^kb_knowledge_base=37109d6c8390571018d5fe55eeaad39d
```

Fields needed for RAG: `number, short_description, text, sys_updated_on`.
The article body (`text`) is HTML and must be cleaned before chunking.

## 8. Verified REST calls

Tick each call after testing it as helpdesk_agent_svc in Postman.

| Call | Method and path | Expected | Verified |
|---|---|---|---|
| Create incident | POST /api/now/table/incident | 201 | [ ] |
| Get by number | GET /api/now/table/incident?sysparm_query=number=INC... | 200 | [ ] |
| Search active | GET /api/now/table/incident?sysparm_query=active=true&sysparm_limit=5 | 200 | [ ] |
| Add work note | PATCH /api/now/table/incident/{sys_id} (work_notes) | 200 | [ ] |
| Add comment | PATCH /api/now/table/incident/{sys_id} (comments) | 200 | [ ] |
| Resolve | PATCH /api/now/table/incident/{sys_id} (state, close_code, close_notes) | 200 | [ ] |
| Reassign | PATCH /api/now/table/incident/{sys_id} (assignment_group) | 200 | [ ] |
| Read KB articles | GET /api/now/table/kb_knowledge with the sync filter | 200, article returned | [x] |

## 9. Lessons learned

- 403 "Data Policy Exception" on resolve means a mandatory field is missing or
  its value is not an accepted choice value (here: close_code).
- An empty list from the Table API can mean "not allowed to see", not
  "does not exist". Knowledge access is also controlled by each knowledge base's
  user criteria, not only by roles.
- "Insufficient rights to query records" on sys_choice is expected for the
  service user. Metadata tables are read as admin and stored in configuration.
- Machine identity type turns on Web service access only automatically.

## 10. Rebuild steps if the PDI is reclaimed

1. Request a new PDI at developer.servicenow.com and set the admin password.
2. Recreate the five assignment groups.
3. Create helpdesk_agent_svc (Identity type Machine) with roles itil and knowledge.
4. Create the three demo callers.
5. Create the NexusDesk knowledge base, the user criteria and the read access.
6. Re-run the seed scripts (Phase 5) to reload articles and incidents.
7. Update every sys_id in this file and in the configuration.
