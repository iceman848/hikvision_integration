import frappe


def after_install():
    create_employee_hikvision_field()


def create_employee_hikvision_field():
    if not frappe.db.exists("DocType", "Employee"):
        return

    if frappe.db.exists(
        "Custom Field",
        {
            "dt": "Employee",
            "fieldname": "hikvision_employee_id",
        },
    ):
        return

    frappe.get_doc(
        {
            "doctype": "Custom Field",
            "dt": "Employee",
            "fieldname": "hikvision_employee_id",
            "label": "Hikvision Employee ID",
            "fieldtype": "Data",
            "insert_after": "employee_name",
            "unique": 1,
            "description": "Employee ID used by Hikvision attendance devices.",
        }
    ).insert(ignore_permissions=True)

    frappe.db.commit()