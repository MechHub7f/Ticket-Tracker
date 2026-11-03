# Compliance Notes

How Ticket Tracker supports the record-keeping, privacy, and dietary-safety
expectations that apply to care facilities in New Hampshire — and what the
facility must still do.

> **This is technical documentation, not legal advice.** Rules differ by
> facility type (assisted living, nursing, independent living). The
> administrator is responsible for confirming that your use of this software
> satisfies your facility's obligations under NH law (e.g. RSA 151-E for
> assisted living, He-P 800 administrative rules) and any federal HIPAA
> requirements that apply to you.

## What the software enforces

### 1. Consent before medical data
The `residents` table carries a **consent date**. The server refuses to save
allergies or diet restrictions for a resident unless a consent date is on
file. The consent record itself (signed form, physician order) must be kept by
the facility; the app records the date it was obtained.

### 2. Role separation (least privilege)
- **Staff** can work tickets, check statuses, and run bulk item actions, but
  cannot create, edit, or delete residents (medical data), manage accounts, or
  change retention settings.
- **Administrators** handle residents, consent dates, accounts, buildings, the
  retention setting, and purging.
- Staff listings only include tickets for **currently active** residents.
  Historical/inactive-resident data requires an administrator.

### 3. Audit trail
Every meaningful action is written to the `audit_log` table with the acting
user, timestamp, action name, and a detail line, including:
- resident create/update (medical-data edits noted),
- bulk add / remove / replace across tickets,
- allergy-guard **overrides** (recorded, never silent),
- settings changes (retention window) and purge runs,
- logins.

### 4. Allergy/diet guard on ticket edits
Adding or replacing an item is checked against each resident's documented
allergies and diet tags. Conflicting changes are returned as a warning and
**not applied** unless an authorized user explicitly confirms — and that
confirmation is logged with their identity.

### 5. Data retention and purge
Tickets are never deleted automatically. Administrators can configure a
retention window (default **7 years**) and run a purge that removes tickets for
**inactive residents only**, past the cutoff. Active residents' records are
never removed by the purge.

### 6. Security controls
- Sessions use HttpOnly cookies with a 12-hour expiry; passwords are hashed
  with PBKDF2-SHA256.
- All state-changing requests are rejected for cross-site origins.
- The API never mixes medical data into anonymous responses.

## What the facility must still do

- Keep the signed consent forms or physician orders that back each recorded
  consent date.
- Use HTTPS in production if the server is reachable beyond a trusted LAN (see
  docs/DEPLOYMENT.md).
- Back up `data/ticket_tracker.db` regularly and store backups securely.
- Train staff on the allergy-guard workflow and audit the log periodically.
- Have your compliance/privacy officer verify this setup against your facility
  type's specific NH and federal requirements.
