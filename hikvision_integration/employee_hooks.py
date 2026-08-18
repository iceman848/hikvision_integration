import frappe


def validate_hikvision_employee_id(doc, method=None):
    """
    Enforces uniqueness of hikvision_employee_id, but only among
    non-blank values - unlike a DB-level unique index, this correctly
    allows any number of employees to have no Hikvision ID at all.

    Wire this up in hooks.py:

        doc_events = {
            "Employee": {
                "validate": "hikvision_integration.employee_hooks.validate_hikvision_employee_id"
            }
        }
    """
    if doc.hikvision_employee_id:
        # Strip and write back the cleaned value, not just compare
        # stripped - otherwise "12345" and " 12345 " could be stored
        # as distinct values even though they should be treated (and
        # matched against incoming device events) as the same ID.
        doc.hikvision_employee_id = doc.hikvision_employee_id.strip()

    if not doc.hikvision_employee_id:
        return

    duplicate = frappe.db.exists(
        "Employee",
        {
            "hikvision_employee_id": doc.hikvision_employee_id,
            "name": ["!=", doc.name],
        },
    )

    if duplicate:
        frappe.throw(
            f"Hikvision Employee ID '{doc.hikvision_employee_id}' is "
            f"already assigned to another employee ({duplicate})."
        )