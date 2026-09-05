"""
erp_base/rbac_constants.py — resource/action vocabulary for role permissions,
and the default permission matrix seeded for each of pos_app.Role's fixed
presets (salesperson, manager, accountant, purchasing, owner).

Kept intentionally simpler than a full per-feature ACL: one entry per module
(RESOURCES) crossed with a handful of generic actions (ACTIONS), rather than
hundreds of per-screen permission keys. That's the granularity the tenant
roles this was modeled after (Sales Person / Manager / Accountant) actually
need — "can this role touch Purchases at all" is the real-world question,
not "can this role delete a purchase-order line item".
"""

RESOURCES = {
    "SALES": "sales",
    "PURCHASES": "purchases",
    "INVENTORY": "inventory",
    "POS": "pos",
    "ACCOUNTING": "accounting",
    "CONTACTS": "contacts",
    "REPORTS": "reports",
    "SETTINGS": "settings",
}

ACTIONS = {
    "READ": "read",
    "CREATE": "create",
    "UPDATE": "update",
    "DELETE": "delete",
}

ALL_RESOURCES = list(RESOURCES.values())
ALL_ACTIONS = list(ACTIONS.values())


def full_access() -> dict:
    return {resource: {action: True for action in ALL_ACTIONS} for resource in ALL_RESOURCES}


def no_access() -> dict:
    return {resource: {action: False for action in ALL_ACTIONS} for resource in ALL_RESOURCES}


def access(*, read=None, write=None, resources=ALL_RESOURCES) -> dict:
    """Shorthand for building a permission dict: `read` are resources with
    read-only access, `write` are resources with full read/create/update/delete."""
    read = set(read or [])
    write = set(write or [])
    result = no_access()
    for resource in resources:
        if resource in write:
            result[resource] = {action: True for action in ALL_ACTIONS}
        elif resource in read:
            result[resource] = {**result[resource], "read": True}
    return result


# ── Default permission matrix per fixed role preset ─────────────────────────
DEFAULT_ROLE_PERMISSIONS = {
    "owner": full_access(),
    "manager": access(
        write=[
            RESOURCES["SALES"], RESOURCES["PURCHASES"], RESOURCES["INVENTORY"],
            RESOURCES["POS"], RESOURCES["CONTACTS"],
        ],
        read=[RESOURCES["ACCOUNTING"], RESOURCES["REPORTS"], RESOURCES["SETTINGS"]],
    ),
    "accountant": access(
        write=[RESOURCES["ACCOUNTING"]],
        read=[RESOURCES["SALES"], RESOURCES["PURCHASES"], RESOURCES["INVENTORY"], RESOURCES["REPORTS"], RESOURCES["CONTACTS"]],
    ),
    "salesperson": access(
        write=[RESOURCES["SALES"], RESOURCES["POS"], RESOURCES["CONTACTS"]],
        read=[RESOURCES["INVENTORY"], RESOURCES["REPORTS"]],
    ),
    "purchasing": access(
        write=[RESOURCES["PURCHASES"], RESOURCES["CONTACTS"]],
        read=[RESOURCES["INVENTORY"], RESOURCES["REPORTS"]],
    ),
}

DEFAULT_ROLE_DESCRIPTIONS = {
    "owner": "Full access to every module, including settings and role permissions.",
    "manager": "Runs day-to-day operations across sales, purchases, inventory, and POS; read-only on accounting.",
    "accountant": "Manages accounting (invoices, bills, payments, ledgers); read-only elsewhere.",
    "salesperson": "Takes sales orders and POS sales; read-only on inventory and reports.",
    "purchasing": "Manages purchase orders and vendors; read-only on inventory and reports.",
}
