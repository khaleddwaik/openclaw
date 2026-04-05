---
name: odoo-safe
description: Odoo 17/18/19 ERP connector — Sales, CRM, Purchase, Inventory, Projects, HR, Fleet, Manufacturing, Calendar, eCommerce (80+ operations). Fully self-contained via XML-RPC HTTP calls. No background services. All destructive operations require explicit user confirmation.
---

# Odoo ERP Connector (Safe Edition)

Full-featured Odoo 17/18/19 integration via direct XML-RPC HTTP calls. No compiled plugin, no background services, no webhook server, no polling. Every operation is triggered only by the user.

---

## Configuration

Read from environment or config file. Required keys (camelCase):

| Key | Env var | Description |
|---|---|---|
| `url` | `ODOO_URL` | Odoo base URL, e.g. `http://localhost:8069` |
| `db` | `ODOO_DB` | Database name |
| `username` | `ODOO_USERNAME` | User email |
| `apiKey` | `ODOO_API_KEY` | API key from Odoo Settings → Users → Access Tokens |

Optional:

| Key | Default | Description |
|---|---|---|
| `timeout` | `60` | Request timeout in seconds |
| `maxRetries` | `3` | Retries on network failure |
| `logLevel` | `INFO` | Log verbosity |

**How to get an API key:**
1. Log in to Odoo
2. Go to Settings → Users & Companies → Users
3. Open your user record
4. Scroll to Access Tokens → Generate Token
5. Copy the token

---

## Connection Health Check

Before any operation, optionally verify connectivity.

### Config check (no network)

Validate that all required config keys are present and non-empty: `url`, `db`, `username`, `apiKey`. Report any missing keys. Do not make any HTTP call.

### Live connection test

```
POST {url}/xmlrpc/2/common
Content-Type: text/xml

<?xml version='1.0'?>
<methodCall>
  <methodName>version</methodName>
  <params/>
</methodCall>
```

Returns a struct with `server_version`, `server_version_info`, `server_serie`, `protocol_version`.
Report the server version to the user. If the call fails, report the connection error and check config.

---

## XML-RPC Protocol

All Odoo API calls use XML-RPC over HTTP POST. Two endpoints exist:

| Endpoint | Purpose |
|---|---|
| `{url}/xmlrpc/2/common` | Authentication only |
| `{url}/xmlrpc/2/object` | All data operations |

### Step 1 — Authenticate (get uid)

Call once per session. Returns an integer `uid` used in every subsequent call.

```
POST {url}/xmlrpc/2/common
Content-Type: text/xml

<?xml version='1.0'?>
<methodCall>
  <methodName>authenticate</methodName>
  <params>
    <param><value><string>{db}</string></value></param>
    <param><value><string>{username}</string></value></param>
    <param><value><string>{apiKey}</string></value></param>
    <param><value><struct/></value></param>
  </params>
</methodCall>
```

Successful response returns `<value><int>2</int></value>` (the uid).
If authentication fails, response is `<value><boolean>0</boolean></value>` — raise an authentication error.

Cache the uid for the session. Re-authenticate if a subsequent call returns a fault with code 100.

### Step 2 — Data Calls (execute_kw)

All data operations use `execute_kw` on the object endpoint:

```
POST {url}/xmlrpc/2/object
Content-Type: text/xml

<?xml version='1.0'?>
<methodCall>
  <methodName>execute_kw</methodName>
  <params>
    <param><value><string>{db}</string></value></param>
    <param><value><int>{uid}</int></value></param>
    <param><value><string>{apiKey}</string></value></param>
    <param><value><string>{model}</string></value></param>
    <param><value><string>{method}</string></value></param>
    <param><value><array><data>{positional_args}</data></array></value></param>
    <param><value><struct>{keyword_args}</struct></value></param>
  </params>
</methodCall>
```

### XML-RPC Value Encoding

| Python/JS type | XML encoding |
|---|---|
| String | `<value><string>text</string></value>` |
| Integer | `<value><int>42</int></value>` |
| Float | `<value><double>3.14</double></value>` |
| Boolean true | `<value><boolean>1</boolean></value>` |
| Boolean false | `<value><boolean>0</boolean></value>` |
| List/Array | `<value><array><data>...items...</data></array></value>` |
| Dict/Struct | `<value><struct><member><name>key</name><value>...</value></member></struct></value>` |
| None/False | `<value><boolean>0</boolean></value>` |

### Parsing Responses

A successful response wraps the return value in:
```xml
<methodResponse><params><param><value>RETURN_VALUE</value></param></params></methodResponse>
```

A fault response looks like:
```xml
<methodResponse><fault><value><struct>
  <member><name>faultCode</name><value><int>1</int></value></member>
  <member><name>faultString</name><value><string>Error message here</string></value></member>
</struct></value></fault></methodResponse>
```

Extract `faultCode` and `faultString` for error handling.

### Retry Logic

On network errors (timeout, connection refused): retry up to `maxRetries` times with 1-second backoff.
On Odoo fault codes: do NOT retry — raise the appropriate typed error immediately.

---

## Domain Filter Syntax

Domains are lists of conditions ANDed together by default. Each condition is a 3-element list: `[field, operator, value]`.

### Operators

| Operator | Meaning |
|---|---|
| `=` | Equals |
| `!=` | Not equals |
| `ilike` | Case-insensitive contains |
| `not ilike` | Case-insensitive does not contain |
| `in` | Value in list |
| `not in` | Value not in list |
| `>` | Greater than |
| `>=` | Greater than or equal |
| `<` | Less than |
| `<=` | Less than or equal |
| `=like` | SQL LIKE pattern |
| `child_of` | Subtree (for hierarchical models) |

### Logical Operators

Prefix conditions with `&` (AND, default) or `|` (OR) or `!` (NOT) in Polish notation:

```python
# Records where name contains "Acme" OR name contains "Corp"
["|", ["name", "ilike", "Acme"], ["name", "ilike", "Corp"]]

# Records where state = "draft" AND amount > 1000
["&", ["state", "=", "draft"], ["amount_total", ">", 1000]]

# Records that are NOT cancelled
["!", ["state", "=", "cancel"]]
```

Empty domain `[]` returns all records.

---

## Relational Field Syntax

### Many2one (foreign key)
Write the related record's integer ID:
```python
{"partner_id": 42}
```

### One2many / Many2many (record sets)
Use command tuples in lists:

| Command | Format | Meaning |
|---|---|---|
| Create and link | `[0, 0, {values}]` | Create a new related record and link it |
| Link existing | `[4, id, 0]` | Link an existing record |
| Unlink | `[3, id, 0]` | Unlink (don't delete) |
| Delete | `[2, id, 0]` | Delete the related record |
| Replace all | `[6, 0, [ids]]` | Replace all links with this list |
| Clear all | `[5, 0, 0]` | Remove all links |

Example — create a sale order with two lines:
```python
{
  "partner_id": 42,
  "order_line": [
    [0, 0, {"product_id": 7, "product_uom_qty": 10, "price_unit": 49.99}],
    [0, 0, {"product_id": 8, "product_uom_qty": 5,  "price_unit": 25.00}]
  ]
}
```

---

## Core Operations

### search_read — Search and return records

Method: `search_read`
Positional args: `[domain]`
Keyword args: `{fields: [...], limit: N, offset: N, order: "field asc/desc"}`

XML-RPC positional args section:
```xml
<value><array><data>
  <value><array><data>
    <!-- domain condition: ["state", "=", "draft"] -->
    <value><array><data>
      <value><string>state</string></value>
      <value><string>=</string></value>
      <value><string>draft</string></value>
    </data></array></value>
  </data></array></value>
</data></array></value>
```

Keyword args section (fields + limit):
```xml
<value><struct>
  <member><name>fields</name><value><array><data>
    <value><string>id</string></value>
    <value><string>name</string></value>
    <value><string>state</string></value>
  </data></array></value></member>
  <member><name>limit</name><value><int>100</int></value></member>
</struct></value>
```

Returns: list of dicts. Many2one fields return `[id, display_name]`.

**Hard cap: never request more than 100 records.** Use date filters for large datasets.

### search — Get IDs only

Method: `search`
Positional args: `[domain]`
Keyword args: `{limit: N}`

Returns: list of integer IDs.

### create — Create a record

**Always ask the user for confirmation before creating. Show exactly what will be created.**

Method: `create`
Positional args: `[{field: value, ...}]`
Keyword args: `{}`

Returns: integer ID of the new record.

XML example — creating a partner:
```xml
<!-- positional args -->
<value><array><data>
  <value><struct>
    <member><name>name</name><value><string>Acme Corp</string></value></member>
    <member><name>is_company</name><value><boolean>1</boolean></value></member>
    <member><name>email</name><value><string>contact@acme.com</string></value></member>
  </struct></value>
</data></array></value>
<!-- keyword args -->
<value><struct/></value>
```

### write — Update a record

**Tell the user which record and which fields will change. Ask for confirmation.**

Method: `write`
Positional args: `[[id1, id2, ...], {field: value, ...}]`
Keyword args: `{}`

Returns: `true` on success.

### unlink — Delete records

**ALWAYS require explicit typed confirmation before deleting. State exactly which record(s) will be permanently deleted. Never delete in bulk without listing every record. Only proceed after the user confirms.**

Method: `unlink`
Positional args: `[[id1, id2, ...]]`
Keyword args: `{}`

Returns: `true` on success.

Confirmation prompt format:
```
⚠️ This will permanently delete:
  - {Model}: "{record_name}" (ID {id})

Type "yes, delete it" to confirm, or "cancel" to abort.
```

### execute_kw — Workflow / State Transitions

Executes a model method (workflow action). Confirm state change with user before calling.

Method: any model method name
Positional args: `[[id]]`
Keyword args: `{}`

Tell the user the current state and the resulting state before executing.

---

## Allowed Models

Only operate on these models. Refuse any request for a model not in this list.

| Model | Purpose |
|---|---|
| `res.partner` | Customers and suppliers |
| `sale.order` | Sales orders and quotations |
| `sale.order.line` | Sales order lines |
| `account.move` | Invoices, bills, and journal entries |
| `account.move.line` | Invoice and journal entry lines |
| `account.payment` | Payments |
| `account.payment.term` | Payment terms (read-only) |
| `account.journal` | Journals (read-only) |
| `account.account` | Chart of accounts (read-only) |
| `account.tax` | Taxes (read-only) |
| `product.template` | Product definitions |
| `product.product` | Product variants |
| `stock.quant` | Stock quantities |
| `crm.lead` | Leads and opportunities |
| `purchase.order` | Purchase orders |
| `purchase.order.line` | Purchase order lines |
| `project.project` | Projects |
| `project.task` | Tasks |
| `account.analytic.line` | Timesheets |
| `hr.employee` | Employees |
| `hr.department` | Departments |
| `hr.expense` | Expenses |
| `hr.expense.sheet` | Expense reports |
| `mrp.bom` | Bills of Materials |
| `mrp.bom.line` | BOM component lines |
| `mrp.production` | Manufacturing orders |
| `fleet.vehicle` | Vehicles |
| `fleet.vehicle.odometer` | Odometer readings |
| `calendar.event` | Calendar events |
| `res.users` | Users (read-only: resolve names to IDs) |
| `product.category` | Product categories (read-only) |
| `crm.stage` | CRM pipeline stages (read-only) |
| `project.task.type` | Task stages (read-only) |
| `uom.uom` | Units of measure (read-only) |
| `stock.move` | Stock movements (read-only) |
| `stock.picking` | Delivery orders and receipts |
| `stock.warehouse.orderpoint` | Reorder rules |
| `hr.leave` | Leave requests |
| `hr.leave.type` | Leave types (read-only) |
| `fleet.vehicle.log.services` | Fleet service records |
| `website` | Website (read-only: resolve website ID) |

---

## Model Field Reference

### res.partner — Customers / Suppliers

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required |
| `is_company` | boolean | True for companies |
| `email` | char | |
| `phone` | char | |
| `mobile` | char | |
| `street` | char | |
| `city` | char | |
| `zip` | char | |
| `country_id` | many2one | `res.country` |
| `customer_rank` | integer | >0 = customer |
| `supplier_rank` | integer | >0 = vendor |
| `vat` | char | Tax ID |
| `website` | char | |
| `comment` | text | Internal notes |

Search customers: `[["customer_rank", ">", 0]]`
Search vendors: `[["supplier_rank", ">", 0]]`

### sale.order — Quotations / Sales Orders

| Field | Type | Notes |
|---|---|---|
| `partner_id` | many2one | Required. `res.partner` |
| `date_order` | datetime | Order date |
| `validity_date` | date | Expiry date for quotation |
| `order_line` | one2many | `sale.order.line` |
| `state` | selection | `draft`, `sent`, `sale`, `done`, `cancel` |
| `note` | text | Terms and conditions |
| `user_id` | many2one | Salesperson. `res.users` |

**sale.order.line fields:**

| Field | Type | Notes |
|---|---|---|
| `product_id` | many2one | Required. `product.product` |
| `product_uom_qty` | float | Required. Quantity |
| `price_unit` | float | Unit price |
| `name` | char | Description (auto-filled from product) |
| `discount` | float | Discount % |

**Workflow methods:**
- `action_confirm` — draft → sale (confirmed)
- `action_cancel` — → cancel
- `action_draft` — cancel → draft

### account.move — Invoices / Bills

| Field | Type | Notes |
|---|---|---|
| `partner_id` | many2one | Required. `res.partner` |
| `move_type` | selection | `out_invoice` (customer invoice), `in_invoice` (vendor bill), `out_refund`, `in_refund` |
| `invoice_date` | date | Invoice date |
| `invoice_date_due` | date | Due date |
| `invoice_line_ids` | one2many | `account.move.line` |
| `state` | selection | `draft`, `posted`, `cancel` |
| `payment_state` | selection | `not_paid`, `in_payment`, `paid`, `partial` |
| `ref` | char | Reference number |
| `narration` | text | Notes |

**account.move.line fields:**

| Field | Type | Notes |
|---|---|---|
| `product_id` | many2one | `product.product` |
| `quantity` | float | Quantity |
| `price_unit` | float | Unit price |
| `name` | char | Description |
| `discount` | float | Discount % |
| `account_id` | many2one | Accounting account (auto-filled from product) |

**Workflow methods:**
- `action_post` — draft → posted
- `button_cancel` — → cancel
- `button_draft` — cancel → draft

**Journal entry (manual):**

Set `move_type` to `entry` for a manual journal entry instead of an invoice. Requires `journal_id` and balanced `line_ids` (debit = credit).

### account.payment — Payments

Used to register a payment against a posted invoice or bill.

| Field | Type | Notes |
|---|---|---|
| `payment_type` | selection | `outbound` (pay vendor), `inbound` (receive from customer) |
| `partner_type` | selection | `customer`, `supplier` |
| `partner_id` | many2one | `res.partner` |
| `amount` | float | Required. Payment amount |
| `currency_id` | many2one | `res.currency`. Defaults to company currency |
| `journal_id` | many2one | Required. `account.journal`. Use bank or cash journal |
| `date` | date | Payment date |
| `ref` | char | Memo / reference |
| `state` | selection | `draft`, `posted`, `sent`, `reconciled`, `cancelled` |

**Workflow methods:**
- `action_post` — draft → posted (confirms the payment)
- `action_cancel` — → cancelled
- `action_draft` — cancelled → draft

**To link a payment to a specific invoice**, use the reconciliation flow after posting:
1. Post the payment via `action_post`
2. Call `js_assign_outstanding_credit` on the invoice with the payment's move line ID, or use the `account.move` method `js_assign_outstanding_credit`

**Shortcut — pay an invoice directly:**

Call `_get_reconciled_info_JSON_values` on `account.move` to check existing payments, or use:
```python
execute_kw("account.move", "action_register_payment", [[invoice_id]], {})
```
This opens Odoo's built-in payment wizard context. For API use, create `account.payment` directly then reconcile.

**Find the bank journal ID:**
```python
search_read("account.journal",
  [["type", "in", ["bank", "cash"]]],
  ["id", "name", "type"],
  limit=10
)
```

### account.payment.term — Payment Terms (read-only)

| Field | Type | Notes |
|---|---|---|
| `name` | char | e.g. "30 days", "Immediate Payment" |
| `note` | text | Description shown on invoice |
| `line_ids` | one2many | Installment lines |

Search: `search_read("account.payment.term", [], ["id", "name"])`
Use `id` in `invoice_payment_term_id` field on `account.move`.

### account.journal — Journals (read-only)

| Field | Type | Notes |
|---|---|---|
| `name` | char | Journal name |
| `type` | selection | `sale`, `purchase`, `cash`, `bank`, `general` |
| `code` | char | Short code (e.g. INV, BNK) |
| `currency_id` | many2one | Journal currency |
| `default_account_id` | many2one | Default account |

Common searches:
- Sales journal: `[["type", "=", "sale"]]`
- Bank/cash for payments: `[["type", "in", ["bank", "cash"]]]`
- Purchase journal: `[["type", "=", "purchase"]]`

### account.account — Chart of Accounts (read-only)

| Field | Type | Notes |
|---|---|---|
| `name` | char | Account name |
| `code` | char | Account code (e.g. 1000, 4000) |
| `account_type` | selection | `asset_receivable`, `liability_payable`, `income`, `expense`, etc. |
| `currency_id` | many2one | Account currency |

Search receivable accounts: `[["account_type", "=", "asset_receivable"]]`
Search expense accounts: `[["account_type", "=", "expense"]]`

### account.tax — Taxes (read-only)

| Field | Type | Notes |
|---|---|---|
| `name` | char | Tax name |
| `amount` | float | Tax rate (e.g. 15 for 15%) |
| `amount_type` | selection | `percent`, `fixed`, `division` |
| `type_tax_use` | selection | `sale`, `purchase`, `none` |
| `active` | boolean | |

Search sales taxes: `[["type_tax_use", "=", "sale"], ["active", "=", true]]`
Use `tax_ids` field on `account.move.line` to apply taxes: `[[6, 0, [tax_id]]]`

### product.template — Products

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required |
| `type` | selection | `consu` (consumable), `product` (storable), `service` |
| `list_price` | float | Sales price |
| `standard_price` | float | Cost |
| `categ_id` | many2one | `product.category` |
| `default_code` | char | Internal reference |
| `barcode` | char | |
| `uom_id` | many2one | Unit of measure. `uom.uom` |
| `description` | text | Description |
| `active` | boolean | |
| `sale_ok` | boolean | Can be sold |
| `purchase_ok` | boolean | Can be purchased |

### stock.quant — Stock Levels

Read-only for stock queries.

| Field | Type | Notes |
|---|---|---|
| `product_id` | many2one | `product.product` |
| `location_id` | many2one | Stock location |
| `quantity` | float | On-hand quantity |
| `reserved_quantity` | float | Reserved |

Search stock: `[["location_id.usage", "=", "internal"]]` to filter internal stock locations only.

### crm.lead — Leads / Opportunities

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required. Lead/opportunity name |
| `partner_id` | many2one | `res.partner` (optional) |
| `contact_name` | char | Contact name if no partner |
| `email_from` | char | Email |
| `phone` | char | |
| `expected_revenue` | float | Expected value |
| `probability` | float | Win probability 0–100 |
| `stage_id` | many2one | `crm.stage`. Pipeline stage |
| `user_id` | many2one | Salesperson |
| `type` | selection | `lead` or `opportunity` |
| `description` | text | Notes |
| `date_deadline` | date | Expected close date |

Search stages: `search_read("crm.stage", [], ["id", "name"])` then use name to match.

**Workflow methods:**
- `action_set_won` — mark as won
- `action_set_lost` — mark as lost
- `convert_opportunity` — lead → opportunity

### purchase.order — Purchase Orders

| Field | Type | Notes |
|---|---|---|
| `partner_id` | many2one | Required. Vendor. `res.partner` |
| `date_order` | datetime | Order date |
| `order_line` | one2many | `purchase.order.line` |
| `state` | selection | `draft`, `sent`, `purchase`, `done`, `cancel` |
| `notes` | text | Terms |
| `user_id` | many2one | Purchaser |

**purchase.order.line fields:**

| Field | Type | Notes |
|---|---|---|
| `product_id` | many2one | Required. `product.product` |
| `product_qty` | float | Required. Quantity |
| `price_unit` | float | Unit price |
| `name` | char | Description |
| `date_planned` | datetime | Planned receipt date |

**Workflow methods:**
- `button_confirm` — draft → purchase (confirmed)
- `button_cancel` — → cancel
- `button_draft` — cancel → draft

### project.project — Projects

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required |
| `user_id` | many2one | Project manager |
| `partner_id` | many2one | Customer |
| `date_start` | date | |
| `date` | date | Deadline |
| `description` | text | |
| `active` | boolean | |
| `privacy_visibility` | selection | `followers`, `employees`, `portal` |

### project.task — Tasks

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required |
| `project_id` | many2one | Required. `project.project` |
| `user_ids` | many2many | Assignees. `res.users` |
| `stage_id` | many2one | `project.task.type` |
| `priority` | selection | `0` (normal), `1` (urgent) |
| `date_deadline` | datetime | |
| `description` | text | |
| `tag_ids` | many2many | Tags |

### account.analytic.line — Timesheets

| Field | Type | Notes |
|---|---|---|
| `project_id` | many2one | Required |
| `task_id` | many2one | `project.task` |
| `employee_id` | many2one | `hr.employee` |
| `date` | date | Required |
| `unit_amount` | float | Hours logged |
| `name` | char | Description. Required |

### hr.employee — Employees

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required |
| `department_id` | many2one | `hr.department` |
| `job_title` | char | |
| `job_id` | many2one | `hr.job` |
| `work_email` | char | |
| `mobile_phone` | char | |
| `work_phone` | char | |
| `parent_id` | many2one | Manager. `hr.employee` |
| `coach_id` | many2one | Coach. `hr.employee` |
| `address_id` | many2one | Work address |

### hr.department — Departments

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required |
| `parent_id` | many2one | Parent department |
| `manager_id` | many2one | `hr.employee` |

### hr.expense — Expenses

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required. Description |
| `employee_id` | many2one | Required. `hr.employee` |
| `product_id` | many2one | Expense category product |
| `total_amount` | float | Amount |
| `currency_id` | many2one | Currency |
| `date` | date | Expense date |
| `sheet_id` | many2one | `hr.expense.sheet` |

### mrp.bom — Bills of Materials

| Field | Type | Notes |
|---|---|---|
| `product_tmpl_id` | many2one | Required. `product.template` |
| `product_id` | many2one | Specific variant (optional) |
| `product_qty` | float | Quantity produced. Default 1 |
| `type` | selection | `normal`, `phantom` (kit) |
| `bom_line_ids` | one2many | `mrp.bom.line` |

**mrp.bom.line fields:**

| Field | Type | Notes |
|---|---|---|
| `product_id` | many2one | Required. Component. `product.product` |
| `product_qty` | float | Required. Quantity needed |
| `product_uom_id` | many2one | Unit of measure |

### mrp.production — Manufacturing Orders

| Field | Type | Notes |
|---|---|---|
| `product_id` | many2one | Required. `product.product` |
| `product_qty` | float | Required. Quantity to produce |
| `bom_id` | many2one | `mrp.bom` (auto-fills components) |
| `date_planned_start` | datetime | Planned start |
| `state` | selection | `draft`, `confirmed`, `progress`, `to_close`, `done`, `cancel` |

**Workflow methods:**
- `action_confirm` — draft → confirmed
- `button_plan` — schedule
- `button_scrap` — scrap
- `button_mark_done` — → done

### fleet.vehicle — Vehicles

| Field | Type | Notes |
|---|---|---|
| `name` | char | Auto-generated from brand + model |
| `license_plate` | char | Required |
| `brand_id` | many2one | `fleet.vehicle.model.brand` |
| `model_id` | many2one | `fleet.vehicle.model` |
| `state_id` | many2one | `fleet.vehicle.state` |
| `driver_id` | many2one | Driver. `res.partner` |
| `color` | char | |
| `acquisition_date` | date | |

### fleet.vehicle.odometer — Odometer Readings

| Field | Type | Notes |
|---|---|---|
| `vehicle_id` | many2one | Required. `fleet.vehicle` |
| `value` | float | Required. Odometer reading |
| `date` | date | Reading date |
| `unit` | selection | `km`, `mi` |

### stock.picking — Delivery Orders / Receipts

| Field | Type | Notes |
|---|---|---|
| `name` | char | Auto-generated reference |
| `partner_id` | many2one | `res.partner` |
| `picking_type_id` | many2one | Operation type (incoming/outgoing) |
| `origin` | char | Source document (e.g. PO/SO reference) |
| `state` | selection | `draft`, `waiting`, `confirmed`, `assigned`, `done`, `cancel` |
| `scheduled_date` | datetime | |
| `move_ids` | one2many | `stock.move` lines |

Search receipts: `[["picking_type_code", "=", "incoming"]]`
Search deliveries: `[["picking_type_code", "=", "outgoing"]]`

**Workflow methods:**
- `action_confirm` — draft → confirmed
- `action_assign` — check availability
- `button_validate` — → done (validate receipt/delivery)
- `action_cancel` — → cancel

### stock.move — Stock Movements (read-only)

| Field | Type | Notes |
|---|---|---|
| `product_id` | many2one | `product.product` |
| `product_uom_qty` | float | Quantity |
| `location_id` | many2one | Source location |
| `location_dest_id` | many2one | Destination location |
| `state` | selection | `draft`, `confirmed`, `assigned`, `done`, `cancel` |
| `date` | datetime | |
| `origin` | char | Source document |

Use for tracking stock movement history. Read-only — do not create or modify directly.

### stock.warehouse.orderpoint — Reorder Rules

| Field | Type | Notes |
|---|---|---|
| `product_id` | many2one | Required. `product.product` |
| `location_id` | many2one | Stock location |
| `product_min_qty` | float | Minimum quantity (triggers reorder) |
| `product_max_qty` | float | Maximum quantity (reorder up to) |
| `qty_multiple` | float | Order in multiples of |
| `active` | boolean | |

### hr.leave — Leave Requests

| Field | Type | Notes |
|---|---|---|
| `employee_id` | many2one | Required. `hr.employee` |
| `holiday_status_id` | many2one | Required. Leave type. `hr.leave.type` |
| `date_from` | datetime | Required. Start |
| `date_to` | datetime | Required. End |
| `name` | char | Description/reason |
| `state` | selection | `draft`, `confirm`, `validate1`, `validate`, `refuse` |
| `number_of_days` | float | Computed |

**Workflow methods:**
- `action_confirm` — draft → confirm (submit)
- `action_validate` — → validate (approve)
- `action_refuse` — → refuse (reject)
- `action_draft` — → draft (reset)

Search pending leaves: `[["state", "in", ["confirm", "validate1"]]]`

### fleet.vehicle.log.services — Fleet Service Records

| Field | Type | Notes |
|---|---|---|
| `vehicle_id` | many2one | Required. `fleet.vehicle` |
| `service_type_id` | many2one | Service type |
| `date` | date | Service date |
| `amount` | float | Cost |
| `odometer_id` | many2one | Odometer reading at service |
| `notes` | text | |
| `state` | selection | `new`, `running`, `done`, `cancelled` |

### hr.expense.sheet — Expense Reports

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required. Report title |
| `employee_id` | many2one | Required. `hr.employee` |
| `expense_line_ids` | one2many | `hr.expense` lines |
| `total_amount` | float | Computed total |
| `state` | selection | `draft`, `submit`, `approve`, `post`, `done`, `refuse` |
| `accounting_date` | date | |

**Workflow methods:**
- `action_submit_sheet` — draft → submit
- `approve_expense_sheets` — submit → approve
- `refuse_expense_sheets` — → refuse
- `action_sheet_move_create` — approve → post (create journal entries)

### eCommerce — Website Products and Orders

eCommerce uses existing models with additional website-specific fields.

**Publish/unpublish a product:**

Set `is_published` on `product.template`:
```python
write("product.template", id, {"is_published": True})   # publish
write("product.template", id, {"is_published": False})  # unpublish
```

**eCommerce-specific fields on product.template:**

| Field | Type | Notes |
|---|---|---|
| `is_published` | boolean | Visible on website |
| `website_id` | many2one | Target website (if multi-site) |
| `website_description` | text | Public product description |
| `website_sequence` | integer | Display order |

**Search website orders:**

Website orders are `sale.order` records with a `website_id` set:
```python
search_read("sale.order",
  [["website_id", "!=", False]],
  ["name", "partner_id", "date_order", "amount_total", "state", "website_id"],
  limit=100
)
```

**Search published products:**
```python
search_read("product.template",
  [["is_published", "=", True]],
  ["name", "list_price", "is_published", "website_id"],
  limit=100
)
```

**Get website ID:**
```python
search_read("website", [], ["id", "name"], limit=10)
```

### calendar.event — Calendar Events

| Field | Type | Notes |
|---|---|---|
| `name` | char | Required. Title |
| `start` | datetime | Required. Start datetime |
| `stop` | datetime | Required. End datetime |
| `location` | char | |
| `description` | text | |
| `partner_ids` | many2many | Attendees. `res.partner` |
| `alarm_ids` | many2many | Reminders. `calendar.alarm` |
| `allday` | boolean | All-day event |

---

## Smart Action Patterns

Smart actions resolve names to IDs and handle find-or-create. **Transparency is mandatory:** always tell the user what was found vs. what would be created. Always ask for confirmation before creating any new record.

### find_or_create_partner(name)

1. `search_read("res.partner", [["name", "ilike", name]], ["id", "name"], limit=5)`
2. If results: pick the best match (exact match first, then first `ilike` match). Report: "Found customer: {name} (ID {id})"
3. If no results: inform user → "No customer named '{name}' found. Should I create one?" → wait for confirmation → `create("res.partner", {"name": name, "customer_rank": 1})`

### find_or_create_product(name, type="consu", price=0)

1. `search_read("product.template", [["name", "ilike", name]], ["id", "name", "list_price"], limit=5)`
2. If results: pick best match. Report: "Found product: {name} (ID {id})"
3. If no results: inform user → "No product named '{name}' found. Should I create it? Type: {type}, Price: {price}" → wait for confirmation → `create("product.template", {"name": name, "type": type, "list_price": price})`
4. After creating product.template, get the default `product.product` variant: `search_read("product.product", [["product_tmpl_id", "=", tmpl_id]], ["id"], limit=1)`

### find_or_create_project(name)

1. `search_read("project.project", [["name", "ilike", name]], ["id", "name"], limit=5)`
2. If no results: inform → ask → `create("project.project", {"name": name})`

### find_or_create_department(name)

1. `search_read("hr.department", [["name", "ilike", name]], ["id", "name"], limit=5)`
2. If no results: inform → ask → `create("hr.department", {"name": name})`

### smart_create_quotation(customer_name, lines, options={})

```
1. find_or_create_partner(customer_name)                    → partner_id
2. For each line: find_or_create_product(line.name, ...)   → product_id per line
3. Confirm full order with user:
   "Create quotation for {customer}?
    Lines:
      - {qty}x {product} @ {price} each
    Confirm? (yes/no)"
4. On yes:
   create("sale.order", {
     partner_id: <id>,
     order_line: [[0,0,{product_id, product_uom_qty, price_unit}], ...],
     note: options.note
   })
5. Report: "Created quotation {name} (ID {id}) for {customer}"
```

### smart_create_invoice(customer_name, lines, options={})

```
1. find_or_create_partner(customer_name)
2. For each line: find_or_create_product(...)
3. Confirm with user
4. create("account.move", {
     partner_id: <id>,
     move_type: "out_invoice",
     invoice_date: options.invoice_date,
     invoice_line_ids: [[0,0,{product_id, quantity, price_unit}], ...]
   })
5. Report result
```

### smart_create_purchase(vendor_name, lines, options={})

```
1. find_or_create_partner(vendor_name)  [supplier_rank: 1]
2. For each line: find_or_create_product(...)
3. Confirm with user
4. create("purchase.order", {
     partner_id: <id>,
     order_line: [[0,0,{product_id, product_qty, price_unit}], ...]
   })
5. Report result
```

### smart_create_lead(lead_name, options={})

```
1. If contact name/email given: find_or_create_partner(contact_name) [optional]
2. Confirm with user
3. create("crm.lead", {
     name: lead_name,
     partner_id: <id or False>,
     contact_name: options.contact_name,
     email_from: options.email,
     expected_revenue: options.expected_revenue,
     type: "lead"
   })
4. Report result
```

### smart_create_task(project_name, task_name, options={})

```
1. find_or_create_project(project_name)
2. Confirm with user
3. create("project.task", {
     name: task_name,
     project_id: <id>,
     description: options.description
   })
4. Report result
```

### smart_create_employee(employee_name, options={})

```
1. If department_name given: find_or_create_department(options.department_name)
2. Confirm with user
3. create("hr.employee", {
     name: employee_name,
     department_id: <id or False>,
     job_title: options.job_title,
     work_email: options.email
   })
4. Report result
```

### smart_create_event(title, start_datetime, options={})

```
1. Resolve attendee names to partner IDs via search if given
2. Confirm with user
3. create("calendar.event", {
     name: title,
     start: start_datetime,           // "YYYY-MM-DD HH:MM:SS"
     stop: computed_end_datetime,
     location: options.location,
     partner_ids: [[6, 0, [partner_ids...]]]
   })
4. Report result
```

### smart_create_bom(product_name, components, options={})

```
1. find_or_create_product(product_name)     → product_tmpl_id
2. For each component: find_or_create_product(comp.name) → product_id
3. Confirm with user:
   "Create BOM for {product}?
    Components:
      - {qty}x {component}
    Confirm?"
4. create("mrp.bom", {
     product_tmpl_id: <id>,
     product_qty: options.qty or 1,
     bom_line_ids: [[0,0,{product_id, product_qty}], ...]
   })
5. Report result
```

### smart_register_payment(invoice_id_or_name, options={})

```
1. Search for the invoice if name given:
   search_read("account.move",
     [["name", "=", invoice_name], ["move_type", "in", ["out_invoice","in_invoice"]]],
     ["id", "name", "partner_id", "amount_residual", "state", "payment_state"]
   )
2. Check state = "posted" and payment_state != "paid" — if not, inform user
3. Find bank/cash journal:
   search_read("account.journal", [["type", "in", ["bank","cash"]]], ["id","name","type"])
4. Confirm with user:
   "Register payment of {amount_residual} for invoice {name} ({partner})?
    Journal: {journal_name}
    Date: {today}
    Confirm? (yes/no)"
5. On yes:
   create("account.payment", {
     payment_type: "inbound",          // "outbound" for vendor bill
     partner_type: "customer",         // "supplier" for vendor bill
     partner_id: <partner_id>,
     amount: <amount_residual>,
     journal_id: <journal_id>,
     date: options.date or today,
     ref: options.ref or invoice_name
   })
6. Post the payment:
   execute_kw("account.payment", "action_post", [[payment_id]])
7. Report: "Payment of {amount} registered for invoice {name}. Status: paid."
```

### smart_create_credit_note(invoice_id_or_name, options={})

```
1. Search for the posted invoice
2. Confirm with user:
   "Create a credit note (refund) for invoice {name}?
    Amount: {amount_total}
    Reason: {options.reason or 'not specified'}
    Confirm? (yes/no)"
3. On yes:
   execute_kw("account.move", "action_reverse", [[invoice_id]], {
     "date": options.date or today,
     "journal_id": options.journal_id or False,
     "reason": options.reason or ""
   })
   — This creates and returns a draft credit note (move_type = out_refund)
4. Optionally post it:
   execute_kw("account.move", "action_post", [[credit_note_id]])
5. Report: "Credit note {name} created for invoice {original_name}."
```

### smart_create_manual_journal_entry(journal_name, lines, options={})

```
1. Find journal:
   search_read("account.journal", [["name", "ilike", journal_name]], ["id","name","type"])
2. For each line, resolve account by code or name:
   search_read("account.account", [["code", "=", account_code]], ["id","name"])
3. Verify lines are balanced: sum(debits) == sum(credits)
   If not balanced: inform user and stop
4. Confirm with user — list all lines with account, debit, credit amounts
5. On yes:
   create("account.move", {
     move_type: "entry",
     journal_id: <journal_id>,
     date: options.date or today,
     ref: options.ref,
     line_ids: [[0,0,{
       account_id: <id>,
       name: line.label,
       debit: line.debit or 0,
       credit: line.credit or 0,
       partner_id: line.partner_id or False
     }], ...]
   })
6. Optionally post: execute_kw("account.move", "action_post", [[entry_id]])
7. Report result with entry reference
```

### smart_create_manufacturing_order(product_name, qty, options={})

```
1. find_or_create_product(product_name)
2. Search for BOM: search_read("mrp.bom", [["product_tmpl_id", "=", tmpl_id]], ["id"], limit=1)
3. Confirm with user
4. create("mrp.production", {
     product_id: <variant_id>,
     product_qty: qty,
     bom_id: <bom_id or False>
   })
5. Report result
```

---

## Reporting

Two types of reports are supported: **PDF documents** (printable Odoo reports) and **data reports** (formatted summaries computed from search queries).

---

### PDF Reports

PDF generation uses Odoo's web report endpoint, which requires session-cookie authentication (separate from XML-RPC).

#### Step 1 — Get a session cookie

```
POST {url}/web/session/authenticate
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "db": "{db}",
    "login": "{username}",
    "password": "{apiKey}"
  }
}
```

Extract the `session_id` from the response body (`result.session_id`) or from the `Set-Cookie` header. Use it as a cookie on subsequent report requests: `Cookie: session_id={session_id}`.

#### Step 2 — Download the PDF

```
GET {url}/report/pdf/{report_name}/{ids}
Cookie: session_id={session_id}
```

Returns the raw PDF binary. Save as a `.pdf` file or offer a download link.

#### Common Report Names

| Report | report_name | Model |
|---|---|---|
| Customer Invoice | `account.report_invoice` | `account.move` |
| Vendor Bill | `account.report_invoice` | `account.move` |
| Payment Receipt | `account.report_payment_receipt` | `account.payment` |
| Sales Order | `sale.report_saleorder` | `sale.order` |
| Purchase Order | `purchase.report_purchaseorder` | `purchase.order` |
| Delivery Slip | `stock.report_deliveryslip` | `stock.picking` |
| Manufacturing Order | `mrp.report_mrpproduction` | `mrp.production` |
| Employee Contract | `hr.report_contract` | `hr.contract` |
| Fleet Summary | `fleet.report_fleet_vehicle` | `fleet.vehicle` |
| Project Overview | `project.report_project_task_burndown` | `project.project` |

#### Multiple records in one PDF

Pass a comma-separated list of IDs:
```
GET {url}/report/pdf/account.report_invoice/42,43,44
```

#### HTML preview (no download required)

Replace `/pdf/` with `/html/` for an HTML preview:
```
GET {url}/report/html/account.report_invoice/42
```

---

### Data Reports (Formatted Summaries)

These are computed from `search_read` queries and formatted as readable summaries. No extra authentication needed — uses the standard XML-RPC flow.

#### Invoice Report — All unpaid invoices

```
search_read("account.move",
  [["move_type","=","out_invoice"], ["state","=","posted"], ["payment_state","!=","paid"]],
  ["name","partner_id","invoice_date","invoice_date_due","amount_total","payment_state"],
  limit=100, order="invoice_date_due asc"
)
```

Format as a table: Invoice #, Customer, Date, Due Date, Amount, Status.

#### Invoice Report — Overdue invoices

```
search_read("account.move",
  [["move_type","=","out_invoice"],
   ["state","=","posted"],
   ["payment_state","!=","paid"],
   ["invoice_date_due","<","{today}"]],
  ["name","partner_id","invoice_date_due","amount_residual"],
  limit=100, order="invoice_date_due asc"
)
```

Use today's date in `YYYY-MM-DD` format. Report total outstanding amount.

#### Revenue Report — Sales this month/period

```
search_read("sale.order",
  [["state","in",["sale","done"]], ["date_order",">=","{period_start}"], ["date_order","<=","{period_end}"]],
  ["name","partner_id","date_order","amount_total","user_id"],
  limit=100
)
```

Sum `amount_total` across results for total revenue. Group by `user_id` or `partner_id` for breakdowns.

#### CRM Pipeline Report

```
search_read("crm.lead",
  [["type","=","opportunity"], ["active","=",true]],
  ["name","partner_id","expected_revenue","probability","stage_id","user_id"],
  limit=100
)
```

Group by `stage_id` and sum `expected_revenue` per stage. Show weighted pipeline using `probability`.

#### Stock / Inventory Report — Low stock

```
search_read("stock.quant",
  [["location_id.usage","=","internal"]],
  ["product_id","quantity","reserved_quantity"],
  limit=100
)
```

Compute available = `quantity - reserved_quantity`. Flag products where available < reorder point (requires cross-referencing `product.template` `reordering_rules` or `orderpoint_ids`).

#### Purchase Report — Open POs

```
search_read("purchase.order",
  [["state","in",["draft","sent","purchase"]]],
  ["name","partner_id","date_order","amount_total","state"],
  limit=100
)
```

#### Project / Timesheet Report — Hours by project

```
search_read("account.analytic.line",
  [["project_id","!=",false], ["date",">=","{period_start}"]],
  ["project_id","task_id","employee_id","unit_amount","date"],
  limit=100
)
```

Sum `unit_amount` grouped by `project_id` and optionally `employee_id`.

#### HR Report — Pending expense reports

```
search_read("hr.expense.sheet",
  [["state","in",["draft","submit"]]],
  ["name","employee_id","total_amount","state","date"],
  limit=100
)
```

#### Manufacturing Report — Active production orders

```
search_read("mrp.production",
  [["state","in",["confirmed","progress"]]],
  ["name","product_id","product_qty","date_planned_start","state"],
  limit=100
)
```

#### Accounting Report — Payments this period

```
search_read("account.payment",
  [["state","=","posted"], ["date",">=","{period_start}"], ["date","<=","{period_end}"]],
  ["name","partner_id","amount","payment_type","journal_id","date","ref"],
  limit=100, order="date desc"
)
```

Group by `payment_type` to show inbound vs outbound totals.

#### Accounting Report — Outstanding receivables

```
search_read("account.move",
  [["move_type","=","out_invoice"], ["state","=","posted"], ["payment_state","in",["not_paid","partial"]]],
  ["name","partner_id","invoice_date_due","amount_total","amount_residual"],
  limit=100, order="invoice_date_due asc"
)
```

Sum `amount_residual` for total outstanding. Highlight records past due.

#### Fleet Report — All vehicles with last odometer

```
search_read("fleet.vehicle",
  [],
  ["name","license_plate","driver_id","state_id","last_odometer","last_odometer_unit"],
  limit=100
)
```

---

### Invoice + Report Workflow (end-to-end)

When the user asks to create an invoice and get a report:

```
1. smart_create_invoice(...)          → invoice ID (e.g. 87)
2. action_post on the invoice         → state: draft → posted
3. Confirm with user: "Invoice posted. Generate PDF report?"
4. GET session cookie via /web/session/authenticate
5. GET {url}/report/pdf/account.report_invoice/87
6. Return PDF to user
```

Always post the invoice (step 2) before generating the PDF — Odoo will refuse to render a PDF for a draft invoice.

---

## Workflow Methods by Model

| Model | Method | Transition |
|---|---|---|
| `sale.order` | `action_confirm` | draft → sale |
| `sale.order` | `action_cancel` | → cancel |
| `sale.order` | `action_draft` | cancel → draft |
| `account.move` | `action_post` | draft → posted |
| `account.move` | `button_cancel` | → cancel |
| `account.move` | `button_draft` | cancel → draft |
| `account.move` | `action_reverse` | create credit note/refund |
| `account.payment` | `action_post` | draft → posted |
| `account.payment` | `action_cancel` | → cancelled |
| `account.payment` | `action_draft` | cancelled → draft |
| `purchase.order` | `button_confirm` | draft → purchase |
| `purchase.order` | `button_cancel` | → cancel |
| `purchase.order` | `button_draft` | cancel → draft |
| `crm.lead` | `action_set_won` | → won |
| `crm.lead` | `action_set_lost` | → lost |
| `crm.lead` | `convert_opportunity` | lead → opportunity |
| `mrp.production` | `action_confirm` | draft → confirmed |
| `mrp.production` | `button_mark_done` | → done |
| `mrp.production` | `action_cancel` | → cancel |
| `stock.picking` | `action_confirm` | draft → confirmed |
| `stock.picking` | `action_assign` | check availability |
| `stock.picking` | `button_validate` | → done |
| `stock.picking` | `action_cancel` | → cancel |
| `hr.leave` | `action_confirm` | draft → confirm (submit) |
| `hr.leave` | `action_validate` | → validate (approve) |
| `hr.leave` | `action_refuse` | → refuse |
| `hr.expense.sheet` | `action_submit_sheet` | draft → submit |
| `hr.expense.sheet` | `approve_expense_sheets` | submit → approve |
| `hr.expense.sheet` | `refuse_expense_sheets` | → refuse |
| `sale.order` | `action_quotation_send` | send quotation by email |

---

## Command Examples

### Sales & Quotations
- "Create a quotation for Acme Corp with 10 Widgets at $50 each"
- "Confirm sales order SO00042"
- "Show me all draft quotations from the past week"
- "What's the total revenue from completed orders this month?"

### CRM
- "Create a lead for Rocky, email rocky@example.com, potential $50k deal"
- "Move lead #47 to Qualified stage"
- "Show me the full sales pipeline with all open opportunities"
- "What leads are at proposal stage?"

### Purchasing
- "Create a PO for 500 widgets from Supplier ABC"
- "Confirm purchase order PO00123"
- "Show all pending purchase orders"
- "What's on order that's overdue?"

### Inventory & Products
- "Create a new product: TestWidget, $25 price"
- "Show products with stock below 20 units"
- "What's the stock level for Widget X?"
- "Search for all consumable products"

### Invoicing & Accounting
- "Create an invoice for Acme Corp with 5 units at $50 each"
- "Post invoice INV-001"
- "Register a payment for invoice INV-001"
- "Mark invoice INV-002 as paid via bank transfer"
- "Create a credit note for invoice INV-003"
- "Show me all unpaid invoices"
- "What invoices are overdue?"
- "Show all available payment terms"
- "Create a manual journal entry: debit account 1000 for $500, credit account 4000 for $500"
- "What's the balance on account 1100?"
- "Show all bank and cash journals"

### Projects & Tasks
- "Create a project called Website Redesign"
- "Create a task 'Fix login button' in Website Redesign project"
- "Show me all tasks assigned to me"
- "Log 3 hours of work on task #42"

### HR
- "Create employee John Smith, job title Developer"
- "Create department Engineering"
- "Show all employees in Engineering"
- "Submit expense report for $45.99"

### Fleet
- "Create vehicle: Tesla Model 3, license plate TESLA-001"
- "Log odometer reading: 50,000 miles for vehicle #1"
- "Show all vehicles"

### Manufacturing
- "Create BOM: Widget contains 3 Components A and 2 Components B"
- "Create manufacturing order: produce 50 Widgets"
- "Confirm production order #1"
- "Show all in-progress manufacturing orders"

### Calendar
- "Create meeting: Team Standup, tomorrow at 10am, 1 hour"
- "Show me my meetings for next week"
- "Schedule a 2-hour planning session with the team"

### eCommerce
- "Publish Widget X to the website"
- "Show me all website orders from this week"
- "What products are published on the website?"
- "Unpublish Product Y from the website"

### Leave Management
- "Submit a leave request for John from March 10 to March 14"
- "Show all pending leave requests"
- "Approve leave request #42"
- "What leave requests are waiting for approval?"

### Inventory — Reorder Rules
- "Set reorder point for Widget X: min 10, max 50"
- "Show all products with reorder rules"
- "What products are below their reorder point?"

### Fleet Services
- "Log a service for vehicle Tesla-001: oil change, $120"
- "Show all service records for vehicle #3"
- "What fleet services are scheduled this month?"

### Expense Reports
- "Submit expense report for John Smith"
- "Show pending expense reports"
- "Approve expense report #5"

### Deliveries & Receipts
- "Show all pending receipts"
- "Validate receipt for purchase order PO00123"
- "Show deliveries scheduled for today"

---

## Error Handling

| Fault code | Error type | Action |
|---|---|---|
| `100` | Authentication failed | Re-authenticate or report bad credentials |
| `1` with "Access Denied" | Permission denied | Report user lacks permission for this operation |
| `1` with "Record not found" | Record not found | Report the ID does not exist |
| `1` with "ValidationError" | Validation error | Report the specific field and reason |
| Network timeout | Connection error | Retry up to `maxRetries` times, then report connection failure |

Always surface the `faultString` to the user in plain language. Do not expose raw XML or stack traces.

---

## Troubleshooting

**Connection issues:** Verify `url`, `db`, `username`, `apiKey`. Check Odoo is running at `{url}/web`.

**Authentication errors:** Regenerate API key in Odoo Settings → Users → Access Tokens. Verify username is in email format. Confirm database name matches exactly.

**Missing field errors:** Field names must match Odoo version exactly. Check model definition in Odoo Settings → Technical → Database Structure → Models. Some fields are read-only (state, computed) — use workflow methods instead.

**Smart action fuzzy match:** Searches only the `name` field with `ilike`. If multiple records match, the first result is used. For exact matching, search with `["name", "=", exact_name]` or use `id` directly.

**Large datasets:** Use date range filters — e.g. `[["date_order", ">=", "2026-01-01"]]`. Results are capped at 100 records.

---

## Security Rules (Non-Negotiable)

1. **No background services.** No polling loop, no webhook listener, no persistent connection. Every action is triggered by the user, executes, and terminates.
2. **No arbitrary model access.** Only operate on models in the Allowed Models table. Refuse all others.
3. **Confirm before creating.** Always show the user what will be created and wait for explicit confirmation.
4. **Confirm before updating.** Show which record and which fields change before writing.
5. **Confirm before deleting.** Show the exact record name and ID. Require the user to type confirmation. Never bulk-delete without listing every record.
6. **Confirm workflow transitions.** Show current state → new state before executing.
7. **Report transparently.** Always state which records were found vs. created in every smart action response.

---

**Odoo Versions:** 17, 18, 19
**Protocol:** XML-RPC over HTTP (request-driven, no background services)
**Destructive operations:** Require explicit user confirmation every time
