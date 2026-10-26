# Reference product: Fleetwise

A fleet-management SaaS for logistics and delivery companies. The rebuild replaces it. Facts below are
from the reference's own code, ops runbooks and contracts, pinned at the reference commit.

## Shape
- Django 4.2 monolith (Python), one PostgreSQL 14 primary with two read replicas (6 TB), Celery workers on
  RabbitMQ, a React single-page app, deployed on AWS ECS. About 410k lines.
- 1,900 business tenants, about 38,000 fleet-manager users, about 40,000 tracked vehicles.
- The rebuild team is 14 engineers. Go and Nuxt are the org's stack.

## Identity
- Fleet managers sign in with email and password; Django sessions in a cookie.
- 140 enterprise tenants sign in through their own corporate identity provider instead: SAML 2.0 today
  (Azure AD and Okta), and three of them have asked for OpenID Connect. Those tenants also require
  automated user provisioning and deprovisioning from their IdP (SCIM). Both are written into their
  contracts, and the account team lists them as renewal blockers.
- Twelve integration partners call the REST API with per-tenant API keys. No partner uses OAuth today.

## Data
- PostgreSQL only. 640 tables, nine years old, bigint auto-increment primary keys, hard deletes.
- Row counts: `trips` 2.1 billion, `invoices` 90 million, everything else under 400 million.
- All tenant data carries `tenant_id`; isolation is enforced in application code.
- Attachments (photos, signed delivery receipts) already live in S3, 40 TB.
- Single region (eu-west-1). No data-residency requirement beyond EU hosting.

## Telemetry and events
- Vehicles send GPS and engine telemetry over MQTT to a gateway, which publishes to RabbitMQ. Sustained
  8,000 messages per second, peaks near 20,000. Messages for one vehicle must be processed in order.
  Losing more than 0.1% is unacceptable (it breaks mileage billing).
- Consumers write telemetry into a day-partitioned PostgreSQL table, 14 days hot, then archived to S3.
- Business events (trip started, invoice issued, driver assigned) run at about 40 per second. Duplicates
  are harmless where consumers are idempotent. About 25 business-event consumers exist today.

## Operations and NFRs
- Datadog for APM, logs and metrics. Every request carries a request id, but the id is not propagated into
  Celery jobs, so job failures cannot be tied back to a request.
- No readiness probe today: two deploys in the last year served traffic before migrations had finished.
- Targets for the rebuild: availability 99.9%, p95 API latency 400 ms, SOC 2 Type II, tenant isolation
  verified by test.
