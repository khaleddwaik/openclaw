"""
Odoo ERP API — Safe Edition
XML-RPC client implementing all operations described in SKILL.md.
Uses only Python standard library (xmlrpc.client, urllib, json, os, datetime).
Loads credentials from .env in the same directory or from environment variables.
"""

import xmlrpc.client
import os
import json
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_env():
    """Load .env from the skill directory, falling back to os.environ."""
    skill_dir = Path(__file__).parent
    env_file = skill_dir / ".env"
    file_env = {}

    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    file_env[key.strip()] = value.strip()

    return {
        "url":      os.environ.get("ODOO_URL",      file_env.get("ODOO_URL",      "")),
        "db":       os.environ.get("ODOO_DB",       file_env.get("ODOO_DB",       "")),
        "username": os.environ.get("ODOO_USERNAME", file_env.get("ODOO_USERNAME", "")),
        "api_key":  os.environ.get("ODOO_API_KEY",  file_env.get("ODOO_API_KEY",  "")),
    }


# ---------------------------------------------------------------------------
# Core client
# ---------------------------------------------------------------------------

class OdooAPI:
    def __init__(self):
        config = _load_env()
        self.url      = config["url"].rstrip("/")
        self.db       = config["db"]
        self.username = config["username"]
        self.api_key  = config["api_key"]
        self.uid      = None
        self._common  = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._models  = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    # --- Authentication ---

    def authenticate(self):
        self.uid = self._common.authenticate(self.db, self.username, self.api_key, {})
        if not self.uid:
            raise PermissionError(
                "Authentication failed. Check ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY."
            )
        return self.uid

    def _ensure_auth(self):
        if not self.uid:
            self.authenticate()

    def test_connection(self):
        """Return server version info. No authentication required."""
        return self._common.version()

    def health_check(self):
        """Validate config keys are present, then test live connection."""
        missing = [k for k in ("url", "db", "username", "api_key")
                   if not getattr(self, k)]
        if missing:
            return {"ok": False, "error": f"Missing config: {', '.join(missing)}"}
        try:
            version = self.test_connection()
            return {"ok": True, "server_version": version.get("server_version"), "detail": version}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --- Low-level execute ---

    def execute(self, model, method, args, kwargs=None):
        self._ensure_auth()
        return self._models.execute_kw(
            self.db, self.uid, self.api_key,
            model, method, args, kwargs or {}
        )

    # --- CRUD ---

    def search_read(self, model, domain=None, fields=None, limit=100, offset=0, order=None):
        kwargs = {"limit": min(limit, 100), "offset": offset}
        if fields:
            kwargs["fields"] = fields
        if order:
            kwargs["order"] = order
        return self.execute(model, "search_read", [domain or []], kwargs)

    def search(self, model, domain=None, limit=100):
        return self.execute(model, "search", [domain or []], {"limit": min(limit, 100)})

    def read(self, model, ids, fields=None):
        kwargs = {}
        if fields:
            kwargs["fields"] = fields
        if isinstance(ids, int):
            ids = [ids]
        return self.execute(model, "read", [ids], kwargs)

    def create(self, model, values):
        return self.execute(model, "create", [values])

    def write(self, model, ids, values):
        if isinstance(ids, int):
            ids = [ids]
        return self.execute(model, "write", [ids, values])

    def unlink(self, model, ids):
        if isinstance(ids, int):
            ids = [ids]
        return self.execute(model, "unlink", [ids])

    def workflow(self, model, method, record_id):
        return self.execute(model, method, [[record_id]])

    def fields_get(self, model, attributes=None):
        return self.execute(model, "fields_get", [],
                            {"attributes": attributes or ["string", "type", "required"]})

    # -----------------------------------------------------------------------
    # Find-or-create primitives
    # -----------------------------------------------------------------------

    def find_or_create_partner(self, name, is_supplier=False):
        results = self.search_read(
            "res.partner", [["name", "ilike", name]], ["id", "name"], limit=5
        )
        if results:
            exact = [r for r in results if r["name"].lower() == name.lower()]
            partner = exact[0] if exact else results[0]
            return {"partner": partner, "created": False}

        values = {"name": name}
        values["supplier_rank" if is_supplier else "customer_rank"] = 1
        new_id = self.create("res.partner", values)
        return {"partner": {"id": new_id, "name": name}, "created": True}

    def find_or_create_product(self, name, product_type="consu", price=0.0):
        results = self.search_read(
            "product.template", [["name", "ilike", name]],
            ["id", "name", "list_price"], limit=5
        )
        if results:
            exact = [r for r in results if r["name"].lower() == name.lower()]
            tmpl = exact[0] if exact else results[0]
            variants = self.search_read(
                "product.product", [["product_tmpl_id", "=", tmpl["id"]]], ["id"], limit=1
            )
            return {
                "product": tmpl,
                "product_id": variants[0]["id"] if variants else None,
                "created": False,
            }

        new_id = self.create("product.template", {
            "name": name, "type": product_type, "list_price": price
        })
        variants = self.search_read(
            "product.product", [["product_tmpl_id", "=", new_id]], ["id"], limit=1
        )
        return {
            "product": {"id": new_id, "name": name, "list_price": price},
            "product_id": variants[0]["id"] if variants else None,
            "created": True,
        }

    def find_or_create_project(self, name):
        results = self.search_read(
            "project.project", [["name", "ilike", name]], ["id", "name"], limit=5
        )
        if results:
            exact = [r for r in results if r["name"].lower() == name.lower()]
            return {"project": exact[0] if exact else results[0], "created": False}
        new_id = self.create("project.project", {"name": name})
        return {"project": {"id": new_id, "name": name}, "created": True}

    def find_or_create_department(self, name):
        results = self.search_read(
            "hr.department", [["name", "ilike", name]], ["id", "name"], limit=5
        )
        if results:
            exact = [r for r in results if r["name"].lower() == name.lower()]
            return {"department": exact[0] if exact else results[0], "created": False}
        new_id = self.create("hr.department", {"name": name})
        return {"department": {"id": new_id, "name": name}, "created": True}

    # -----------------------------------------------------------------------
    # Smart Actions
    # -----------------------------------------------------------------------

    def smart_create_quotation(self, customer_name, lines, options=None):
        options = options or {}
        p = self.find_or_create_partner(customer_name)
        partner = p["partner"]

        order_lines, product_results = [], []
        for line in lines:
            pr = self.find_or_create_product(
                line.get("name", ""), price=line.get("price_unit", 0)
            )
            product_results.append(pr)
            order_lines.append([0, 0, {
                "product_id":      pr["product_id"],
                "product_uom_qty": line.get("quantity", 1),
                "price_unit":      line.get("price_unit", pr["product"]["list_price"]),
            }])

        values = {"partner_id": partner["id"], "order_line": order_lines}
        if options.get("note"):
            values["note"] = options["note"]
        if options.get("validity_date"):
            values["validity_date"] = options["validity_date"]

        order_id = self.create("sale.order", values)
        orders = self.search_read("sale.order", [["id", "=", order_id]], ["name"], limit=1)
        order_name = orders[0]["name"] if orders else str(order_id)

        created = (
            [f"new customer '{customer_name}'"] if p["created"] else []
        ) + [f"new product '{pr['product']['name']}'" for pr in product_results if pr["created"]]

        summary = f"Created quotation {order_name} for {partner['name']}"
        if created:
            summary += f" (also created: {', '.join(created)})"
        return {"order_id": order_id, "order_name": order_name, "partner": partner, "summary": summary}

    def smart_create_invoice(self, customer_name, lines, options=None):
        options = options or {}
        p = self.find_or_create_partner(customer_name)
        partner = p["partner"]

        invoice_lines, product_results = [], []
        for line in lines:
            pr = self.find_or_create_product(
                line.get("name", ""), price=line.get("price_unit", 0)
            )
            product_results.append(pr)
            invoice_lines.append([0, 0, {
                "product_id": pr["product_id"],
                "quantity":   line.get("quantity", 1),
                "price_unit": line.get("price_unit", pr["product"]["list_price"]),
                "name":       line.get("description", line.get("name", pr["product"]["name"])),
            }])

        values = {
            "partner_id":       partner["id"],
            "move_type":        options.get("move_type", "out_invoice"),
            "invoice_line_ids": invoice_lines,
        }
        if options.get("invoice_date"):
            values["invoice_date"] = options["invoice_date"]
        if options.get("invoice_date_due"):
            values["invoice_date_due"] = options["invoice_date_due"]
        if options.get("ref"):
            values["ref"] = options["ref"]
        if options.get("narration"):
            values["narration"] = options["narration"]
        if options.get("payment_term_id"):
            values["invoice_payment_term_id"] = options["payment_term_id"]

        invoice_id = self.create("account.move", values)
        invoices = self.search_read("account.move", [["id", "=", invoice_id]], ["name"], limit=1)
        invoice_name = invoices[0]["name"] if invoices else str(invoice_id)

        created = (
            [f"new customer '{customer_name}'"] if p["created"] else []
        ) + [f"new product '{pr['product']['name']}'" for pr in product_results if pr["created"]]

        summary = f"Created invoice {invoice_name} for {partner['name']}"
        if created:
            summary += f" (also created: {', '.join(created)})"
        return {"invoice_id": invoice_id, "invoice_name": invoice_name, "partner": partner, "summary": summary}

    def smart_create_vendor_bill(self, vendor_name, lines, options=None):
        options = options or {}
        options["move_type"] = "in_invoice"
        return self.smart_create_invoice(vendor_name, lines, options)

    def smart_create_purchase(self, vendor_name, lines, options=None):
        options = options or {}
        p = self.find_or_create_partner(vendor_name, is_supplier=True)
        partner = p["partner"]

        order_lines = []
        for line in lines:
            pr = self.find_or_create_product(line.get("name", ""), price=line.get("price_unit", 0))
            order_lines.append([0, 0, {
                "product_id":   pr["product_id"],
                "product_qty":  line.get("quantity", 1),
                "price_unit":   line.get("price_unit", 0),
                "name":         line.get("name", pr["product"]["name"]),
                "date_planned": options.get("date_planned", str(date.today())),
            }])

        values = {"partner_id": partner["id"], "order_line": order_lines}
        if options.get("notes"):
            values["notes"] = options["notes"]

        po_id = self.create("purchase.order", values)
        pos = self.search_read("purchase.order", [["id", "=", po_id]], ["name"], limit=1)
        po_name = pos[0]["name"] if pos else str(po_id)

        summary = f"Created purchase order {po_name} for vendor {partner['name']}"
        return {"po_id": po_id, "po_name": po_name, "partner": partner, "summary": summary}

    def smart_create_lead(self, lead_name, options=None):
        options = options or {}
        partner_id = False
        if options.get("contact_name") or options.get("email"):
            contact = options.get("contact_name", lead_name)
            pr = self.find_or_create_partner(contact)
            partner_id = pr["partner"]["id"]

        values = {
            "name":       lead_name,
            "type":       options.get("type", "lead"),
            "partner_id": partner_id,
        }
        for src, dst in [("contact_name", "contact_name"), ("email", "email_from"),
                         ("phone", "phone"), ("expected_revenue", "expected_revenue"),
                         ("description", "description"), ("stage_id", "stage_id")]:
            if options.get(src) is not None:
                values[dst] = options[src]

        lead_id = self.create("crm.lead", values)
        summary = f"Created lead '{lead_name}' (ID {lead_id})"
        return {"lead_id": lead_id, "summary": summary}

    def smart_create_task(self, project_name, task_name, options=None):
        options = options or {}
        project_result = self.find_or_create_project(project_name)
        project = project_result["project"]

        values = {"name": task_name, "project_id": project["id"]}
        for src, dst in [("description", "description"), ("deadline", "date_deadline"),
                         ("priority", "priority"), ("stage_id", "stage_id")]:
            if options.get(src) is not None:
                values[dst] = options[src]

        task_id = self.create("project.task", values)
        summary = f"Created task '{task_name}' in project '{project['name']}'"
        if project_result["created"]:
            summary += " (project was created)"
        return {"task_id": task_id, "project": project, "summary": summary}

    def smart_log_timesheet(self, project_name, task_name, employee_name, hours, description, log_date=None):
        project_result = self.find_or_create_project(project_name)
        project_id = project_result["project"]["id"]

        tasks = self.search_read("project.task",
            [["name", "ilike", task_name], ["project_id", "=", project_id]], ["id", "name"], limit=1)
        task_id = tasks[0]["id"] if tasks else False

        employees = self.search_read("hr.employee", [["name", "ilike", employee_name]], ["id"], limit=1)
        employee_id = employees[0]["id"] if employees else False

        values = {
            "project_id":   project_id,
            "task_id":      task_id,
            "employee_id":  employee_id,
            "unit_amount":  hours,
            "name":         description,
            "date":         log_date or str(date.today()),
        }
        line_id = self.create("account.analytic.line", values)
        summary = f"Logged {hours}h on task '{task_name}' in project '{project_name}'"
        return {"line_id": line_id, "summary": summary}

    def smart_create_employee(self, employee_name, options=None):
        options = options or {}
        department_id = False
        if options.get("department_name"):
            dr = self.find_or_create_department(options["department_name"])
            department_id = dr["department"]["id"]

        values = {"name": employee_name}
        if department_id:
            values["department_id"] = department_id
        for src, dst in [("job_title", "job_title"), ("email", "work_email"),
                         ("phone", "work_phone"), ("mobile", "mobile_phone")]:
            if options.get(src):
                values[dst] = options[src]

        emp_id = self.create("hr.employee", values)
        summary = f"Created employee '{employee_name}' (ID {emp_id})"
        return {"employee_id": emp_id, "summary": summary}

    def smart_create_event(self, title, start_datetime, options=None):
        options = options or {}

        stop_datetime = options.get("stop")
        if not stop_datetime:
            duration = options.get("duration", 1)
            start_dt = datetime.strptime(start_datetime, "%Y-%m-%d %H:%M:%S")
            stop_datetime = (start_dt + timedelta(hours=duration)).strftime("%Y-%m-%d %H:%M:%S")

        partner_ids = []
        for name in options.get("attendee_names", []):
            results = self.search_read("res.partner", [["name", "ilike", name]], ["id"], limit=1)
            if results:
                partner_ids.append(results[0]["id"])

        values = {"name": title, "start": start_datetime, "stop": stop_datetime}
        if options.get("location"):
            values["location"] = options["location"]
        if options.get("description"):
            values["description"] = options["description"]
        if partner_ids:
            values["partner_ids"] = [[6, 0, partner_ids]]

        event_id = self.create("calendar.event", values)
        summary = f"Created event '{title}' on {start_datetime}"
        return {"event_id": event_id, "summary": summary}

    def smart_create_bom(self, product_name, components, options=None):
        options = options or {}
        pr = self.find_or_create_product(product_name)
        tmpl_id = pr["product"]["id"]

        bom_lines = []
        for comp in components:
            cpr = self.find_or_create_product(comp.get("name", ""))
            bom_lines.append([0, 0, {
                "product_id":  cpr["product_id"],
                "product_qty": comp.get("quantity", 1),
            }])

        values = {
            "product_tmpl_id": tmpl_id,
            "product_qty":     options.get("quantity", 1),
            "type":            options.get("type", "normal"),
            "bom_line_ids":    bom_lines,
        }
        bom_id = self.create("mrp.bom", values)
        summary = f"Created BOM for '{product_name}' with {len(components)} component(s)"
        return {"bom_id": bom_id, "summary": summary}

    def smart_create_manufacturing_order(self, product_name, qty, options=None):
        options = options or {}
        pr = self.find_or_create_product(product_name)
        product_id = pr["product_id"]
        tmpl_id = pr["product"]["id"]

        boms = self.search_read("mrp.bom", [["product_tmpl_id", "=", tmpl_id]], ["id"], limit=1)
        bom_id = boms[0]["id"] if boms else False

        values = {"product_id": product_id, "product_qty": qty, "bom_id": bom_id}
        if options.get("date_planned_start"):
            values["date_planned_start"] = options["date_planned_start"]

        mo_id = self.create("mrp.production", values)
        mos = self.search_read("mrp.production", [["id", "=", mo_id]], ["name"], limit=1)
        mo_name = mos[0]["name"] if mos else str(mo_id)

        summary = f"Created manufacturing order {mo_name} for {qty}x '{product_name}'"
        return {"mo_id": mo_id, "mo_name": mo_name, "summary": summary}

    # -----------------------------------------------------------------------
    # Accounting smart actions
    # -----------------------------------------------------------------------

    def smart_register_payment(self, invoice_ref, options=None):
        options = options or {}

        invoices = self.search_read(
            "account.move",
            [["name", "=", invoice_ref], ["move_type", "in", ["out_invoice", "in_invoice"]]],
            ["id", "name", "partner_id", "amount_residual", "state", "payment_state", "move_type"],
            limit=1,
        )
        if not invoices:
            return {"error": f"Invoice '{invoice_ref}' not found."}

        inv = invoices[0]
        if inv["state"] != "posted":
            return {"error": f"Invoice '{invoice_ref}' is not posted (state: {inv['state']}). Post it first."}
        if inv["payment_state"] == "paid":
            return {"error": f"Invoice '{invoice_ref}' is already fully paid."}

        journal_id = options.get("journal_id")
        journal_name = ""
        if not journal_id:
            journals = self.search_read(
                "account.journal", [["type", "in", ["bank", "cash"]]], ["id", "name"], limit=1
            )
            if not journals:
                return {"error": "No bank or cash journal found."}
            journal_id   = journals[0]["id"]
            journal_name = journals[0]["name"]

        is_vendor = inv["move_type"] == "in_invoice"
        partner_id = inv["partner_id"][0] if inv["partner_id"] else False

        payment_values = {
            "payment_type": "outbound" if is_vendor else "inbound",
            "partner_type": "supplier" if is_vendor else "customer",
            "partner_id":   partner_id,
            "amount":       inv["amount_residual"],
            "journal_id":   journal_id,
            "date":         options.get("date", str(date.today())),
            "ref":          options.get("ref", inv["name"]),
        }

        payment_id = self.create("account.payment", payment_values)
        self.workflow("account.payment", "action_post", payment_id)

        payments = self.search_read("account.payment", [["id", "=", payment_id]], ["name"], limit=1)
        payment_name = payments[0]["name"] if payments else str(payment_id)

        summary = (
            f"Payment {payment_name} of {inv['amount_residual']} "
            f"registered for invoice {inv['name']} via {journal_name or journal_id}"
        )
        return {"payment_id": payment_id, "payment_name": payment_name, "invoice": inv, "summary": summary}

    def smart_create_credit_note(self, invoice_ref, options=None):
        options = options or {}

        invoices = self.search_read(
            "account.move",
            [["name", "=", invoice_ref], ["move_type", "in", ["out_invoice", "in_invoice"]]],
            ["id", "name", "state"],
            limit=1,
        )
        if not invoices:
            return {"error": f"Invoice '{invoice_ref}' not found."}

        inv = invoices[0]
        if inv["state"] != "posted":
            return {"error": "Invoice must be posted before creating a credit note."}

        reverse_vals = {
            "date":   options.get("date", str(date.today())),
            "reason": options.get("reason", ""),
        }
        if options.get("journal_id"):
            reverse_vals["journal_id"] = options["journal_id"]

        result = self.execute("account.move", "action_reverse", [[inv["id"]]], reverse_vals)
        summary = f"Credit note created for invoice {inv['name']}"
        return {"result": result, "invoice": inv, "summary": summary}

    def smart_create_manual_journal_entry(self, journal_name, lines, options=None):
        options = options or {}

        journals = self.search_read(
            "account.journal", [["name", "ilike", journal_name]], ["id", "name"], limit=1
        )
        if not journals:
            return {"error": f"Journal '{journal_name}' not found."}
        journal_id = journals[0]["id"]

        total_debit  = sum(l.get("debit", 0) for l in lines)
        total_credit = sum(l.get("credit", 0) for l in lines)
        if round(total_debit, 2) != round(total_credit, 2):
            return {"error": f"Journal entry is not balanced: debit {total_debit} ≠ credit {total_credit}"}

        entry_lines = []
        for line in lines:
            accounts = self.search_read(
                "account.account",
                [["code", "=", line.get("account_code", "")]],
                ["id", "name"], limit=1,
            )
            if not accounts:
                accounts = self.search_read(
                    "account.account",
                    [["name", "ilike", line.get("account_name", line.get("account_code", ""))]],
                    ["id", "name"], limit=1,
                )
            if not accounts:
                return {"error": f"Account '{line.get('account_code') or line.get('account_name')}' not found."}

            entry_lines.append([0, 0, {
                "account_id": accounts[0]["id"],
                "name":       line.get("label", ""),
                "debit":      line.get("debit", 0),
                "credit":     line.get("credit", 0),
                "partner_id": line.get("partner_id", False),
            }])

        values = {
            "move_type":  "entry",
            "journal_id": journal_id,
            "date":       options.get("date", str(date.today())),
            "ref":        options.get("ref", ""),
            "line_ids":   entry_lines,
        }

        entry_id = self.create("account.move", values)
        if options.get("post", False):
            self.workflow("account.move", "action_post", entry_id)

        entries = self.search_read("account.move", [["id", "=", entry_id]], ["name"], limit=1)
        entry_name = entries[0]["name"] if entries else str(entry_id)

        summary = f"Created journal entry {entry_name} in '{journals[0]['name']}'"
        return {"entry_id": entry_id, "entry_name": entry_name, "summary": summary}

    # -----------------------------------------------------------------------
    # eCommerce
    # -----------------------------------------------------------------------

    def publish_product(self, product_name, publish=True):
        results = self.search_read(
            "product.template", [["name", "ilike", product_name]], ["id", "name", "is_published"], limit=5
        )
        if not results:
            return {"error": f"Product '{product_name}' not found."}
        exact = [r for r in results if r["name"].lower() == product_name.lower()]
        product = exact[0] if exact else results[0]
        self.write("product.template", product["id"], {"is_published": publish})
        action = "Published" if publish else "Unpublished"
        summary = f"{action} product '{product['name']}' on website"
        return {"product_id": product["id"], "summary": summary}

    def get_website_orders(self, limit=50):
        return self.search_read(
            "sale.order",
            [["website_id", "!=", False]],
            ["name", "partner_id", "date_order", "amount_total", "state", "website_id"],
            limit=limit, order="date_order desc",
        )

    # -----------------------------------------------------------------------
    # Leave management
    # -----------------------------------------------------------------------

    def smart_create_leave(self, employee_name, leave_type_name, date_from, date_to, options=None):
        options = options or {}

        employees = self.search_read("hr.employee", [["name", "ilike", employee_name]], ["id", "name"], limit=1)
        if not employees:
            return {"error": f"Employee '{employee_name}' not found."}
        employee_id = employees[0]["id"]

        leave_types = self.search_read("hr.leave.type", [["name", "ilike", leave_type_name]], ["id", "name"], limit=1)
        if not leave_types:
            return {"error": f"Leave type '{leave_type_name}' not found."}
        leave_type_id = leave_types[0]["id"]

        values = {
            "employee_id":        employee_id,
            "holiday_status_id":  leave_type_id,
            "date_from":          date_from,
            "date_to":            date_to,
            "name":               options.get("reason", ""),
        }
        leave_id = self.create("hr.leave", values)
        summary = f"Created leave request for {employees[0]['name']} from {date_from} to {date_to}"
        return {"leave_id": leave_id, "summary": summary}

    # -----------------------------------------------------------------------
    # Fleet
    # -----------------------------------------------------------------------

    def smart_create_vehicle(self, license_plate, options=None):
        options = options or {}
        values = {"license_plate": license_plate}
        if options.get("model_name"):
            models = self.search_read(
                "fleet.vehicle.model", [["name", "ilike", options["model_name"]]], ["id"], limit=1
            )
            if models:
                values["model_id"] = models[0]["id"]
        if options.get("color"):
            values["color"] = options["color"]
        if options.get("driver_name"):
            dr = self.find_or_create_partner(options["driver_name"])
            values["driver_id"] = dr["partner"]["id"]

        vehicle_id = self.create("fleet.vehicle", values)
        summary = f"Created vehicle with license plate '{license_plate}' (ID {vehicle_id})"
        return {"vehicle_id": vehicle_id, "summary": summary}

    def log_odometer(self, vehicle_ref, value, unit="km", log_date=None):
        vehicles = self.search_read(
            "fleet.vehicle", [["license_plate", "ilike", vehicle_ref]], ["id", "name"], limit=1
        )
        if not vehicles:
            vehicles = self.search_read("fleet.vehicle", [["id", "=", int(vehicle_ref)]], ["id", "name"], limit=1)
        if not vehicles:
            return {"error": f"Vehicle '{vehicle_ref}' not found."}

        vehicle_id = vehicles[0]["id"]
        odo_id = self.create("fleet.vehicle.odometer", {
            "vehicle_id": vehicle_id,
            "value":      value,
            "unit":       unit,
            "date":       log_date or str(date.today()),
        })
        summary = f"Logged odometer reading {value} {unit} for vehicle '{vehicles[0]['name']}'"
        return {"odometer_id": odo_id, "summary": summary}

    def log_fleet_service(self, vehicle_ref, amount, options=None):
        options = options or {}
        vehicles = self.search_read(
            "fleet.vehicle", [["license_plate", "ilike", vehicle_ref]], ["id", "name"], limit=1
        )
        if not vehicles:
            return {"error": f"Vehicle '{vehicle_ref}' not found."}

        values = {
            "vehicle_id": vehicles[0]["id"],
            "amount":     amount,
            "date":       options.get("date", str(date.today())),
        }
        if options.get("notes"):
            values["notes"] = options["notes"]

        service_id = self.create("fleet.vehicle.log.services", values)
        summary = f"Logged service record for vehicle '{vehicles[0]['name']}': {amount}"
        return {"service_id": service_id, "summary": summary}

    # -----------------------------------------------------------------------
    # Reporting queries
    # -----------------------------------------------------------------------

    def report_unpaid_invoices(self):
        return self.search_read(
            "account.move",
            [["move_type", "=", "out_invoice"], ["state", "=", "posted"], ["payment_state", "!=", "paid"]],
            ["name", "partner_id", "invoice_date", "invoice_date_due", "amount_total", "amount_residual", "payment_state"],
            limit=100, order="invoice_date_due asc",
        )

    def report_overdue_invoices(self):
        today = str(date.today())
        return self.search_read(
            "account.move",
            [["move_type", "=", "out_invoice"], ["state", "=", "posted"],
             ["payment_state", "!=", "paid"], ["invoice_date_due", "<", today]],
            ["name", "partner_id", "invoice_date_due", "amount_total", "amount_residual"],
            limit=100, order="invoice_date_due asc",
        )

    def report_outstanding_receivables(self):
        return self.search_read(
            "account.move",
            [["move_type", "=", "out_invoice"], ["state", "=", "posted"],
             ["payment_state", "in", ["not_paid", "partial"]]],
            ["name", "partner_id", "invoice_date_due", "amount_total", "amount_residual"],
            limit=100, order="invoice_date_due asc",
        )

    def report_revenue(self, period_start, period_end):
        return self.search_read(
            "sale.order",
            [["state", "in", ["sale", "done"]],
             ["date_order", ">=", period_start], ["date_order", "<=", period_end]],
            ["name", "partner_id", "date_order", "amount_total", "user_id"],
            limit=100,
        )

    def report_crm_pipeline(self):
        return self.search_read(
            "crm.lead",
            [["type", "=", "opportunity"], ["active", "=", True]],
            ["name", "partner_id", "expected_revenue", "probability", "stage_id", "user_id"],
            limit=100,
        )

    def report_low_stock(self):
        return self.search_read(
            "stock.quant",
            [["location_id.usage", "=", "internal"]],
            ["product_id", "quantity", "reserved_quantity"],
            limit=100,
        )

    def report_open_purchase_orders(self):
        return self.search_read(
            "purchase.order",
            [["state", "in", ["draft", "sent", "purchase"]]],
            ["name", "partner_id", "date_order", "amount_total", "state"],
            limit=100,
        )

    def report_timesheet_hours(self, period_start):
        return self.search_read(
            "account.analytic.line",
            [["project_id", "!=", False], ["date", ">=", period_start]],
            ["project_id", "task_id", "employee_id", "unit_amount", "date"],
            limit=100,
        )

    def report_pending_expenses(self):
        return self.search_read(
            "hr.expense.sheet",
            [["state", "in", ["draft", "submit"]]],
            ["name", "employee_id", "total_amount", "state", "date"],
            limit=100,
        )

    def report_active_manufacturing_orders(self):
        return self.search_read(
            "mrp.production",
            [["state", "in", ["confirmed", "progress"]]],
            ["name", "product_id", "product_qty", "date_planned_start", "state"],
            limit=100,
        )

    def report_fleet(self):
        return self.search_read(
            "fleet.vehicle", [],
            ["name", "license_plate", "driver_id", "state_id", "last_odometer", "last_odometer_unit"],
            limit=100,
        )

    def report_payments(self, period_start, period_end):
        return self.search_read(
            "account.payment",
            [["state", "=", "posted"],
             ["date", ">=", period_start], ["date", "<=", period_end]],
            ["name", "partner_id", "amount", "payment_type", "journal_id", "date", "ref"],
            limit=100, order="date desc",
        )

    # -----------------------------------------------------------------------
    # PDF report download
    # -----------------------------------------------------------------------

    def download_pdf_report(self, report_name, record_ids, save_path=None):
        """
        Download a PDF report from Odoo.
        Returns raw bytes. Optionally saves to save_path.
        """
        # Step 1: get session cookie
        auth_payload = json.dumps({
            "jsonrpc": "2.0", "method": "call",
            "params": {"db": self.db, "login": self.username, "password": self.api_key},
        }).encode()

        req = urllib.request.Request(
            f"{self.url}/web/session/authenticate",
            data=auth_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            auth_body = json.loads(resp.read())
            set_cookie = resp.headers.get("Set-Cookie", "")

        session_id = None
        for part in set_cookie.split(";"):
            p = part.strip()
            if p.startswith("session_id="):
                session_id = p.split("=", 1)[1]
                break
        if not session_id:
            session_id = (auth_body.get("result") or {}).get("session_id")
        if not session_id:
            raise RuntimeError("Could not obtain session cookie for PDF generation.")

        # Step 2: download PDF
        if isinstance(record_ids, int):
            record_ids = [record_ids]
        ids_str = ",".join(str(i) for i in record_ids)

        pdf_req = urllib.request.Request(
            f"{self.url}/report/pdf/{report_name}/{ids_str}",
            headers={"Cookie": f"session_id={session_id}"},
        )
        with urllib.request.urlopen(pdf_req) as resp:
            pdf_bytes = resp.read()

        if save_path:
            with open(save_path, "wb") as f:
                f.write(pdf_bytes)

        return pdf_bytes


# ---------------------------------------------------------------------------
# Module-level singleton + convenience functions
# ---------------------------------------------------------------------------

_api = None

def _get_api():
    global _api
    if _api is None:
        _api = OdooAPI()
    return _api


# --- Connection ---
def health_check():                                     return _get_api().health_check()
def test_connection():                                  return _get_api().test_connection()

# --- CRUD ---
def search_read(model, domain=None, fields=None, limit=100, offset=0, order=None):
    return _get_api().search_read(model, domain, fields, limit, offset, order)
def search(model, domain=None, limit=100):              return _get_api().search(model, domain, limit)
def read(model, ids, fields=None):                      return _get_api().read(model, ids, fields)
def create(model, values):                              return _get_api().create(model, values)
def write(model, ids, values):                          return _get_api().write(model, ids, values)
def unlink(model, ids):                                 return _get_api().unlink(model, ids)
def workflow(model, method, record_id):                 return _get_api().workflow(model, method, record_id)
def fields_get(model, attributes=None):                 return _get_api().fields_get(model, attributes)

# --- Find-or-create ---
def find_or_create_partner(name, is_supplier=False):    return _get_api().find_or_create_partner(name, is_supplier)
def find_or_create_product(name, product_type="consu", price=0.0): return _get_api().find_or_create_product(name, product_type, price)
def find_or_create_project(name):                       return _get_api().find_or_create_project(name)
def find_or_create_department(name):                    return _get_api().find_or_create_department(name)

# --- Smart actions ---
def smart_create_quotation(customer_name, lines, options=None):     return _get_api().smart_create_quotation(customer_name, lines, options)
def smart_create_invoice(customer_name, lines, options=None):       return _get_api().smart_create_invoice(customer_name, lines, options)
def smart_create_vendor_bill(vendor_name, lines, options=None):     return _get_api().smart_create_vendor_bill(vendor_name, lines, options)
def smart_create_purchase(vendor_name, lines, options=None):        return _get_api().smart_create_purchase(vendor_name, lines, options)
def smart_create_lead(lead_name, options=None):                     return _get_api().smart_create_lead(lead_name, options)
def smart_create_task(project_name, task_name, options=None):       return _get_api().smart_create_task(project_name, task_name, options)
def smart_log_timesheet(project_name, task_name, employee_name, hours, description, log_date=None): return _get_api().smart_log_timesheet(project_name, task_name, employee_name, hours, description, log_date)
def smart_create_employee(employee_name, options=None):             return _get_api().smart_create_employee(employee_name, options)
def smart_create_event(title, start_datetime, options=None):        return _get_api().smart_create_event(title, start_datetime, options)
def smart_create_bom(product_name, components, options=None):       return _get_api().smart_create_bom(product_name, components, options)
def smart_create_manufacturing_order(product_name, qty, options=None): return _get_api().smart_create_manufacturing_order(product_name, qty, options)
def smart_register_payment(invoice_ref, options=None):              return _get_api().smart_register_payment(invoice_ref, options)
def smart_create_credit_note(invoice_ref, options=None):            return _get_api().smart_create_credit_note(invoice_ref, options)
def smart_create_manual_journal_entry(journal_name, lines, options=None): return _get_api().smart_create_manual_journal_entry(journal_name, lines, options)

# --- eCommerce ---
def publish_product(product_name, publish=True):        return _get_api().publish_product(product_name, publish)
def get_website_orders(limit=50):                       return _get_api().get_website_orders(limit)

# --- Fleet ---
def smart_create_vehicle(license_plate, options=None):  return _get_api().smart_create_vehicle(license_plate, options)
def log_odometer(vehicle_ref, value, unit="km", log_date=None): return _get_api().log_odometer(vehicle_ref, value, unit, log_date)
def log_fleet_service(vehicle_ref, amount, options=None): return _get_api().log_fleet_service(vehicle_ref, amount, options)

# --- Leave ---
def smart_create_leave(employee_name, leave_type_name, date_from, date_to, options=None): return _get_api().smart_create_leave(employee_name, leave_type_name, date_from, date_to, options)

# --- Reports ---
def report_unpaid_invoices():                           return _get_api().report_unpaid_invoices()
def report_overdue_invoices():                          return _get_api().report_overdue_invoices()
def report_outstanding_receivables():                   return _get_api().report_outstanding_receivables()
def report_revenue(period_start, period_end):           return _get_api().report_revenue(period_start, period_end)
def report_crm_pipeline():                              return _get_api().report_crm_pipeline()
def report_low_stock():                                 return _get_api().report_low_stock()
def report_open_purchase_orders():                      return _get_api().report_open_purchase_orders()
def report_timesheet_hours(period_start):               return _get_api().report_timesheet_hours(period_start)
def report_pending_expenses():                          return _get_api().report_pending_expenses()
def report_active_manufacturing_orders():               return _get_api().report_active_manufacturing_orders()
def report_fleet():                                     return _get_api().report_fleet()
def report_payments(period_start, period_end):          return _get_api().report_payments(period_start, period_end)
def download_pdf_report(report_name, record_ids, save_path=None): return _get_api().download_pdf_report(report_name, record_ids, save_path)
