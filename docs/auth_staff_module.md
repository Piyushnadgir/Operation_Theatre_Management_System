# Staff Management and Access Security module (Poorvi)

Requirements: OT-F-030 to OT-F-033 and OT-SR-001 to OT-SR-006. Jira: OTMS-14 to OTMS-18, OTMS-28.

## Endpoints (all under `/api/v1`)

| Method and path | Roles | Purpose | Errors |
|---|---|---|---|
| POST `/auth/login` | public | Log in, returns `{token, role}` | 401 bad credentials, 423 locked |
| POST `/auth/users` | admin | Create a user account | 409 duplicate, 422 invalid |
| POST `/auth/users/{id}/unlock` | admin | Unlock a locked account | 404 |
| POST `/staff` | admin | Add a doctor or nurse | 422 invalid |
| GET `/staff` | admin, scheduler | List active staff (`staff_type`, `specialization`, `include_inactive`) | |
| PUT `/staff/{id}` | admin | Update name or specialization | 404, 422 |
| DELETE `/staff/{id}` | admin | Deactivate (never deletes) | 404 |
| PUT `/staff/{id}/shifts` | admin | Replace a person's shifts | 400 overlap, 404, 422 |
| GET `/staff/{id}/shifts` | admin, scheduler | Read shifts | 404 |
| GET `/staff/{id}/availability?start_time=&end_time=` | admin, scheduler | `{available: true/false}` | 400 bad range, 404 |
| POST `/staff/validate-assignment` | admin, scheduler | Check OT-F-033 for doctors and nurses | 422 |

Every endpoint except `/auth/login` needs a Bearer token (401 without one) and checks the role on the server (403).

## Rules

- Availability = active, on one shift that covers the whole time range, and not in another scheduled or in-progress surgery.
- Assignment (OT-F-033) = exists, active, correct type, on shift for the whole surgery and, for doctors when a specialization is required, matching specialization.
- Lockout (OT-SR-004): 5 failed logins lock the account for 15 minutes. While locked, even the right password gets 423. An admin can unlock.
- Audit log (OT-SR-005): `log_action()` in `app/services/audit_service.py`. Entries cannot be updated or deleted through the application.

## Deviations from the SAD (explain these in the demo)

1. Field names are snake_case (`staff_type`, `start_time`) to match the existing code, not camelCase.
2. Added `POST /auth/users`, `POST /auth/users/{id}/unlock`, `GET /staff/{id}/shifts` and `POST /staff/validate-assignment`. The SAD had no way to create users, unlock accounts, read shifts or pre-check an assignment.
3. Availability also takes existing surgeries into account.
4. Staff responses return the full staff record, not only the id.

## Run

    pip install -r requirements.txt
    python -m app.utils.seed --username admin --role admin     # first user
    uvicorn app.main:app --reload                               # docs at /docs
    pytest                                                      # all tests
    pytest --cov=app --cov-branch --cov-report=term-missing     # coverage and branch coverage

## HTTPS demo (TC-Sec-01)

    openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 30 -subj "/CN=localhost"
    ENFORCE_HTTPS=true uvicorn app.main:app --ssl-keyfile key.pem --ssl-certfile cert.pem --port 8443
    curl -k https://localhost:8443/health
    openssl s_client -connect localhost:8443 -tls1_1     # should be refused
    openssl s_client -connect localhost:8443 -tls1_2     # should connect

(PowerShell: set `$env:ENFORCE_HTTPS="true"` first.) With `ENFORCE_HTTPS=true`, any request that reaches the app over plain HTTP, for example through a proxy, gets 403.

## Hooks for the other modules

Audit a change (3 lines in a router, after the service call succeeds):

    from app.services.audit_service import log_action
    log_action(db, "surgery.cancel", user_id=current_user.get("sub"), entity_type="surgery", entity_id=surgery_id)

Check staff before saving a surgery (in `SurgeryService.create_surgery`, next to the conflict check):

    from app.services.assignment_service import AssignmentService
    issues = AssignmentService(self.db).validate_assignments(doctor_ids, nurse_ids, start_time, end_time)
    if issues:
        return None, issues
