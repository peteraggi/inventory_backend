# LogsInventory Backend — Multi-Tenant SaaS POS API

A Django REST Framework backend that provisions isolated PostgreSQL schemas per client using **django-tenants**. Each business that signs up gets its own schema, its own users, its own inventory, and its own sales data — fully isolated, like Odoo.

---

## Table of Contents

- [Architecture](#architecture)
- [Subscription Plans](#subscription-plans)
- [Getting Started (Development)](#getting-started-development)
- [How Routing Works](#how-routing-works)
- [Full API Reference](#full-api-reference)
  - [Public Endpoints (api.inventory.com)](#public-endpoints)
  - [Auth Endpoints (tenant subdomain)](#auth-endpoints)
  - [POS & Inventory Endpoints (tenant subdomain)](#pos--inventory-endpoints)
- [Onboarding Flow](#onboarding-flow)
- [Authentication Flow](#authentication-flow)
- [Password Reset Flow](#password-reset-flow)
- [Roles & Permissions](#roles--permissions)
- [Offline Sync Flow](#offline-sync-flow)
- [Environment Variables](#environment-variables)
- [Running Migrations](#running-migrations)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    PostgreSQL Server                     │
│                                                         │
│  public schema          acme schema      lagos schema   │
│  ─────────────          ───────────      ────────────   │
│  clients_client         auth_user        auth_user       │
│  clients_domain         pos_store        pos_store       │
│  clients_plan           pos_product      pos_product     │
│  (shared tables)        pos_invoice      pos_invoice     │
│                         ...              ...             │
└─────────────────────────────────────────────────────────┘

Routing (subdomain-based):
  api.inventory.com           → public schema (onboarding, plans)
  acme.api.inventory.com      → acme schema   (auth, POS, reports)
  lagosmart.api.inventory.com → lagosmart schema
```

**Stack:** Django 5 · DRF · django-tenants · PostgreSQL · Redis (cache + Celery) · JWT (simplejwt) · Resend (email) · Docker

---

## Subscription Plans

| Plan       | Stores | Users | Products | Price/month |
|------------|--------|-------|----------|-------------|
| Free       | 1      | 5     | 100      | ₦0          |
| Basic      | 2      | 10    | 500      | TBD         |
| Standard   | 5      | 25    | 2,000    | TBD         |
| Enterprise | ∞      | ∞     | ∞        | TBD         |

New accounts start on a **30-day Free trial**.

---

## Getting Started (Development)

### Prerequisites
- Python 3.13+
- PostgreSQL 14+
- Redis

### Install dependencies

```bash
pip install -r requirements.txt
# requirements must include: django-tenants>=3.5, djangorestframework, djangorestframework-simplejwt,
# drf-yasg, django-filter, django-cors-headers, django-celery-beat, django-celery-results,
# psycopg2-binary, python-decouple, whitenoise, gunicorn, requests, openpyxl
```

### Environment variables

Copy `.env.example` to `.env` (see [Environment Variables](#environment-variables) section).

### Local subdomain routing

Add to `/etc/hosts` (or `C:\Windows\System32\drivers\etc\hosts` on Windows):

```
127.0.0.1   api.inventory.com
127.0.0.1   acme.api.inventory.com
127.0.0.1   testclient.api.inventory.com
```

### Database setup + run

```bash
# 1. Create shared tables (public schema: clients, plans, django internals)
python manage.py migrate_schemas --shared

# 2. Seed subscription plans
python manage.py shell -c "
from inventory_apps.clients.models import SubscriptionPlan
from decimal import Decimal
plans = [
  ('free','Free Trial', 0, 1, 5, 100),
  ('basic','Basic', 5000, 2, 10, 500),
  ('standard','Standard', 15000, 5, 25, 2000),
  ('enterprise','Enterprise', 50000, 999, 9999, 999999),
]
for name, display, price, stores, users, products in plans:
  SubscriptionPlan.objects.get_or_create(name=name, defaults={
    'display_name': display,
    'price_monthly': Decimal(str(price)),
    'max_stores': stores,
    'max_users': users,
    'max_products': products,
    'is_active': True,
  })
print('Plans seeded.')
"

# 3. Run dev server
python manage.py runserver
```

> When you onboard the first client via `POST /onboard/`, django-tenants automatically
> creates the schema and runs all tenant migrations (`migrate_schemas` is called internally).

---

## How Routing Works

django-tenants reads the **subdomain** from every request and switches the active
PostgreSQL schema before the view runs. No code changes needed per tenant.

| Request host                  | Schema used | URL conf used           |
|-------------------------------|-------------|-------------------------|
| `api.inventory.com`           | `public`    | `urls_public.py`        |
| `acme.api.inventory.com`      | `acme`      | `urls.py` (tenant)      |
| `testclient.api.inventory.com`| `testclient`| `urls.py` (tenant)      |

---

## Full API Reference

### Public Endpoints

Base URL: `https://api.inventory.com`

#### List subscription plans
```
GET /plans/
```
Response:
```json
[
  {
    "id": "uuid",
    "name": "free",
    "display_name": "Free Trial",
    "price_monthly": "0.00",
    "max_stores": 1,
    "max_users": 5,
    "max_products": 100,
    "features": {}
  }
]
```

#### Onboard a new business (self-service)
```
POST /onboard/
```
Request:
```json
{
  "business_name": "Acme Retail",
  "contact_name": "John Doe",
  "contact_email": "john@acme.com",
  "password": "secret123",
  "subdomain": "acme",
  "plan": "free",
  "store_name": "Acme HQ",
  "contact_phone": "08012345678"
}
```
`plan` and `store_name` are optional (default: `"free"`, `business_name`).

Response `201`:
```json
{
  "success": true,
  "message": "Your workspace is ready.",
  "tenant": {
    "id": "uuid",
    "business_name": "Acme Retail",
    "subdomain": "acme",
    "api_base_url": "https://acme.api.inventory.com",
    "plan": "free",
    "on_trial": true,
    "trial_ends": "2026-07-12"
  },
  "owner": {
    "email": "john@acme.com",
    "name": "John Doe",
    "tokens": {
      "access": "eyJ...",
      "refresh": "eyJ..."
    }
  }
}
```

After onboarding the owner is **already logged in** — use the tokens immediately.

---

### Auth Endpoints

Base URL: `https://{subdomain}.api.inventory.com`

All auth endpoints are under `/auth/`.

#### Register a new staff member (owner must supply store_id + role_id)
```
POST /auth/register/
```
```json
{
  "name": "Jane Smith",
  "email": "jane@acme.com",
  "password": "pass123",
  "phone": "08011112222",
  "store_id": "uuid-of-store",
  "role_id": "uuid-of-role"
}
```
Response `201`: user data + `verification_required: true`. A 6-digit code is emailed.

#### Verify email
```
POST /auth/verify-email/
```
```json
{ "email": "jane@acme.com", "code": "123456" }
```
Response `200`: JWT tokens (user is now logged in).

#### Resend verification code
```
POST /auth/resend-verification-code/
```
```json
{ "email": "jane@acme.com" }
```

#### Login
```
POST /auth/login/
```
```json
{ "email": "john@acme.com", "password": "secret123" }
```
Response `200`:
```json
{
  "email": "john@acme.com",
  "name": "John Doe",
  "username": "johndoe",
  "user_id": "uuid",
  "store_id": "uuid",
  "store_name": "Acme HQ",
  "role": "owner",
  "tokens": { "access": "eyJ...", "refresh": "eyJ..." }
}
```

#### Refresh access token
```
POST /auth/token/refresh/
```
```json
{ "refresh": "eyJ..." }
```

#### Logout (blacklists refresh token)
```
POST /auth/logout/
Authorization: Bearer <access_token>
```
```json
{ "refresh": "eyJ..." }
```

#### Request password reset code
```
POST /auth/request-reset-email/
```
```json
{ "email": "john@acme.com" }
```
Always returns success (prevents email enumeration). A 6-digit code is emailed.

#### Verify reset code
```
POST /auth/verify-reset-code/
```
```json
{ "email": "john@acme.com", "code": "654321" }
```
Response `200`: `{ "reset_token": "...", "uidb64": "..." }`

#### Set new password
```
PATCH /auth/password-reset-complete/
```
```json
{
  "password": "newpass123",
  "token": "<reset_token from previous step>",
  "uidb64": "<uidb64 from previous step>"
}
```

---

### POS & Inventory Endpoints

Base URL: `https://{subdomain}.api.inventory.com`

All endpoints require `Authorization: Bearer <access_token>` unless noted.

---

#### Stores

```
GET  /pos/stores/          — list all active stores in this tenant (public)
GET  /pos/stores/me/       — current user's store details
```

#### Roles
```
GET  /pos/roles/           — list all roles (public, used during registration)
```

#### User Profile
```
GET    /pos/profile/       — get own profile
PATCH  /pos/profile/       — update own profile (name, phone, bio)
```

---

#### Categories

```
GET    /pos/categories/           — list active categories (store-scoped)
POST   /pos/categories/           — create category
GET    /pos/categories/{id}/      — category detail
PUT    /pos/categories/{id}/      — update category
PATCH  /pos/categories/{id}/      — partial update
DELETE /pos/categories/{id}/      — soft delete (is_active = false)
```

POST/PUT body:
```json
{ "name": "Electronics", "description": "Phones, laptops, accessories", "parent": null }
```

---

#### Products

```
GET    /pos/products/             — list products (store-scoped)
POST   /pos/products/             — create product
GET    /pos/products/low-stock/   — products at or below low_stock_threshold
GET    /pos/products/{id}/        — product detail
PUT    /pos/products/{id}/        — update product
PATCH  /pos/products/{id}/        — partial update
DELETE /pos/products/{id}/        — soft delete
```

Query params for list:
- `search=` — searches name, code, barcode, description
- `category=<uuid>` — filter by category
- `is_active=true/false`
- `low_stock=true` — only low-stock items
- `ordering=name,-price,stock,-created_at`

POST body:
```json
{
  "name": "Samsung Galaxy A54",
  "code": "PHONE-A54",
  "description": "6.4 inch display",
  "category": "uuid-of-category",
  "price": "350000.00",
  "cost": "280000.00",
  "stock": 25,
  "low_stock_threshold": 5,
  "barcode": "8806094374476",
  "image_url": "https://example.com/a54.jpg"
}
```

---

#### Invoices (Sales)

```
GET  /pos/invoices/            — list invoices (salespeople see own; owners/managers see all)
POST /pos/invoices/            — create invoice (sale)
GET  /pos/invoices/{id}/       — invoice detail with items
POST /pos/invoices/bulk-sync/  — sync multiple offline invoices at once
```

Query params for list:
- `sync_status=PENDING/SYNCED/FAILED`
- `start_date=2026-01-01`, `end_date=2026-01-31`
- `ordering=created_at,-total`

POST body (create invoice):
```json
{
  "invoice_number": "INV-001",
  "discount": "0.00",
  "customer_name": "Ade Johnson",
  "customer_phone": "08099998888",
  "customer_email": "",
  "notes": "",
  "items": [
    {
      "product": "uuid-of-product",
      "quantity": 2,
      "price": "350000.00"
    }
  ]
}
```
`invoice_number` is auto-generated if omitted. Stock is decremented automatically.

Bulk sync body:
```json
{
  "invoices": [
    {
      "invoice_number": "INV-OFF-001",
      "salesperson": "uuid-of-user",
      "subtotal": "700000.00",
      "tax": "70000.00",
      "discount": "0.00",
      "total": "770000.00",
      "items": [...]
    }
  ]
}
```

---

#### Dashboard & Reports (owners and managers only)

```
GET /pos/dashboard/stats/         — today/week/month sales, low stock count
GET /pos/reports/sales/           — sales by salesperson
GET /pos/reports/products/        — top selling products
```

Query params for reports:
- `start_date=2026-01-01`
- `end_date=2026-06-30`
- `limit=20` (products report only)

Dashboard response:
```json
{
  "today_sales": "125000.00",
  "invoice_count": 8,
  "top_product": "Samsung Galaxy A54",
  "active_salespeople": 3,
  "week_sales": "890000.00",
  "month_sales": "3450000.00",
  "low_stock_products": 2
}
```

---

#### Sync

```
GET  /pos/sync/status/            — pending invoice count + last sync time
GET  /pos/sync/history/           — last 20 sync log entries
```

---

## Onboarding Flow

```
1. GET  /plans/                     → show plans to prospective customer
2. POST /onboard/                   → create tenant, schema, owner account
   ↳ returns JWT tokens (owner is logged in immediately)
3. GET  {subdomain}.api.inventory.com/pos/stores/   → get store_id
4. GET  {subdomain}.api.inventory.com/pos/roles/    → get role IDs
5. POST {subdomain}.api.inventory.com/auth/register/ → add staff members
6. POST {subdomain}.api.inventory.com/pos/categories/ → create categories
7. POST {subdomain}.api.inventory.com/pos/products/   → add inventory
8. POST {subdomain}.api.inventory.com/pos/invoices/   → start selling
```

---

## Authentication Flow

```
Register → email 6-digit code (30 min, 5 attempts max)
         → POST /auth/verify-email/ → JWT tokens

Login    → POST /auth/login/        → JWT tokens
         Access token: 10 minutes
         Refresh token: 30 days (rolling, blacklisted on rotation)

Refresh  → POST /auth/token/refresh/ → new access + refresh tokens
Logout   → POST /auth/logout/        → refresh token blacklisted
```

---

## Password Reset Flow

```
1. POST /auth/request-reset-email/   { email }
   ↓ 6-digit code emailed (15 min, 3 attempts max)
2. POST /auth/verify-reset-code/     { email, code }
   ↓ returns reset_token + uidb64
3. PATCH /auth/password-reset-complete/  { password, token, uidb64 }
   ↓ password updated, reset session cleared
```

---

## Roles & Permissions

Three roles are seeded automatically on tenant creation:

| Role        | manage_users | manage_products | manage_invoices | view_reports | manage_store |
|-------------|-------------|-----------------|-----------------|--------------|--------------|
| owner       | ✓           | ✓               | ✓               | ✓            | ✓            |
| manager     | ✗           | ✓               | ✓               | ✓            | ✗            |
| salesperson | ✗           | ✗               | ✓ (own only)    | ✗            | ✗            |

Endpoint-level enforcement:
- Dashboard & reports → `owner` or `manager` only
- Invoice list → salespeople see own; owners/managers see all store invoices
- Products/categories → all authenticated users can read; write controlled by role permissions

---

## Offline Sync Flow

The system supports **offline-first** mobile POS devices:

1. Mobile app creates invoices locally with `sync_status: PENDING`
2. When online, POST to `/pos/invoices/bulk-sync/` with all pending invoices
3. Server validates, deducts stock, marks invoices `SYNCED`, logs in `SyncLog`
4. `GET /pos/sync/status/` shows how many are still pending

---

## Environment Variables

```env
# Django
DJANGO_SECRET_KEY=your-secret-key
DEBUG=False

# Database (PostgreSQL)
POSTGRES_DB=logsinventory
POSTGRES_USER=postgres
POSTGRES_PASSWORD=yourpassword
PG_HOST=postgres_db
PG_PORT=5432

# Redis
REDIS_PASSWORD=yourredispassword

# Email via Resend (https://resend.com)
EMAIL_RESEND_API_KEY=re_xxxxxxxxxxxx

# Optional SMTP fallback
EMAIL_SERVER_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
```

---

## Running Migrations

```bash
# Shared schema (public tables: Client, Domain, SubscriptionPlan, Django internals)
python manage.py migrate_schemas --shared

# All tenant schemas (auth, pos tables in every client's schema)
python manage.py migrate_schemas

# Specific tenant only
python manage.py migrate_schemas --schema=acme

# Create a new tenant migration
python manage.py makemigrations authentication
python manage.py makemigrations pos_app
```

> **Never** use plain `python manage.py migrate` — it won't respect the schema split.

---

## Swagger / API Docs

- Public schema: `https://api.inventory.com/` → Swagger UI
- Tenant schema: `https://{subdomain}.api.inventory.com/` → Swagger UI

Both include Bearer token authentication support.

---

**Version:** 1.0.0 — Multi-Tenant SaaS POS  
**Stack:** Django 5 · DRF · django-tenants · PostgreSQL · Redis · JWT · Resend · Docker
