"""Seed Metro City with departments, POs, and sample routed invoices."""
import os
import uuid
from datetime import date, datetime, timedelta

from app import (
    app, db, City, Department, User, VendorInvite, PurchaseOrder, POLine,
    Invoice, InvoiceLineItem, InvoiceActivity, DEPARTMENTS,
)

PASSWORD = "demo123"


def add_po(city, vendor, po_number, dept, lines):
    """lines: list of (line_number, description, budget, category)"""
    po = PurchaseOrder(
        city_id=city.id,
        department_id=dept.id,
        vendor_id=vendor.id,
        po_number=po_number,
    )
    db.session.add(po)
    db.session.flush()
    po_lines = {}
    for line_number, description, budget, category in lines:
        pl = POLine(
            po_id=po.id,
            line_number=line_number,
            description=description,
            budget_amount=budget,
            category=category,
        )
        db.session.add(pl)
        db.session.flush()
        po_lines[line_number] = pl
    return po, po_lines


def seed():
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    pdf = next((f for f in os.listdir(app.config["UPLOAD_FOLDER"]) if f.lower().endswith(".pdf")), None)

    with app.app_context():
        db.drop_all()
        db.create_all()

        city = City(name="Metro City")
        db.session.add(city)
        db.session.flush()

        depts = {}
        for name in DEPARTMENTS:
            d = Department(name=name, city_id=city.id)
            db.session.add(d)
            db.session.flush()
            depts[name] = d

        staff = User(name="Maria Lopez", email="ap@demo.city", role="city_staff", city_id=city.id)
        staff.set_password(PASSWORD)
        db.session.add(staff)

        invite = VendorInvite(
            city_id=city.id,
            vendor_email="vendor@contractor.com",
            vendor_company="Northstar Transit Services",
            token=uuid.uuid4().hex,
            accepted=True,
        )
        db.session.add(invite)
        db.session.flush()

        vendor = User(name="Chris Vendor", email="vendor@contractor.com", role="vendor", city_id=city.id)
        vendor.set_password(PASSWORD)
        db.session.add(vendor)
        db.session.flush()

        _, transit_lines = add_po(
            city, vendor, "PO-1042", depts["Transit"],
            [
                (1, "Materials — shelter parts & hardware", 5000.00, "materials"),
                (2, "Labor — installation & field work", 3000.00, "services"),
                (3, "Sales tax (reserved)", 1040.00, "tax"),
            ],
        )

        _, fire_lines = add_po(
            city, vendor, "PO-0888", depts["Fire"],
            [
                (1, "Equipment service & inspection", 3500.00, "services"),
                (2, "Parts & replacement supplies", 1000.00, "materials"),
                (3, "Sales tax (reserved)", 500.00, "tax"),
            ],
        )

        samples = [
            {
                "inv_num": "INV-7841",
                "po": "PO-1042",
                "dept": depts["Transit"],
                "desc": "Bus shelter maintenance",
                "allocations": [
                    (transit_lines[1], 3820.00),
                    (transit_lines[2], 1000.00),
                    (transit_lines[3], 626.60),
                ],
            },
            {
                "inv_num": "INV-7720",
                "po": "PO-0888",
                "dept": depts["Fire"],
                "desc": "Station equipment service",
                "status": "returned",
                "return_reason": "Tax was charged to the services line — please allocate to the tax line on PO-0888.",
                "allocations": [
                    (fire_lines[1], 2100.00),
                    (fire_lines[2], 380.00),
                    (fire_lines[3], 322.40),
                ],
            },
            {
                "inv_num": "INV-7601",
                "po": None,
                "dept": depts["Finance-AP"],
                "desc": "Annual software license",
                "allocations": [],
                "amount": 8200.0,
                "tax": 13.0,
            },
        ]

        for s in samples:
            if s["allocations"]:
                total = round(sum(amt for _, amt in s["allocations"]), 2)
                amount = total
                tax = 0.0
            else:
                amount = s["amount"]
                tax = s["tax"]
                total = round(amount + amount * tax / 100, 2)

            inv = Invoice(
                vendor_id=vendor.id,
                city_id=city.id,
                department_id=s["dept"].id,
                po_number=s["po"],
                invoice_number=s["inv_num"],
                invoice_date=date.today(),
                amount=amount,
                tax_rate=tax,
                total_amount=total,
                description=s["desc"],
                status=s.get("status", "received"),
                return_reason=s.get("return_reason"),
                pdf_filename=pdf,
                submitted_at=datetime.utcnow() - timedelta(days=2),
            )
            db.session.add(inv)
            db.session.flush()

            for i, (po_line, amt) in enumerate(s["allocations"]):
                db.session.add(InvoiceLineItem(
                    invoice_id=inv.id,
                    po_line_id=po_line.id,
                    amount=amt,
                    sort_order=i,
                ))

            db.session.add(InvoiceActivity(
                invoice_id=inv.id, author_id=vendor.id,
                body=f"{vendor.name} submitted invoice {s['inv_num']}", kind="submission",
            ))
            db.session.add(InvoiceActivity(
                invoice_id=inv.id, body=f"Routed to {s['dept'].name}", kind="system",
            ))
            if s["allocations"]:
                db.session.add(InvoiceActivity(
                    invoice_id=inv.id,
                    body=f"Charged against {len(s['allocations'])} PO line(s) · ${total:,.2f}",
                    kind="system",
                ))
            if s.get("status") == "returned":
                db.session.add(InvoiceActivity(
                    invoice_id=inv.id,
                    author_id=staff.id,
                    body=f"{staff.name} returned to vendor — {s['return_reason']}",
                    kind="note",
                ))

        db.session.commit()
        print("Seeded with PO fund lines + allocations.")
        print("  Demo POs: PO-1042 (Transit), PO-0888 (Fire)")
        print("  Returned invoice: INV-7720 (vendor can resubmit)")
        print(f"  Password: {PASSWORD}")


if __name__ == "__main__":
    seed()
