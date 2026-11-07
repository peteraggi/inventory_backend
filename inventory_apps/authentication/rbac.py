# inventory_apps/authentication/rbac.py
"""
Permission checks shared by the models, the DRF permission classes and the serializers.

The access model follows oas_dev's:

  * A user holds one primary role (User.role) and may hold more (UserRole, soft-revoked).
  * Individual grants (User.permission_overrides) are added on top of the roles.
  * Access is only ever added. Nothing a role or grant gives can be taken away by another.
  * Creating, changing or deleting a resource implies reading it.
  * A module that is switched off for the tenant grants nothing, to anyone.
  * Users can only assign roles and grants that they hold themselves.

Matrix shape, from erp_base.rbac_constants:
    {"inventory": {"read": True, "create": False, "update": True, "delete": False}, ...}
"""
from inventory_apps.erp_base.rbac_constants import ALL_ACTIONS, ALL_RESOURCES

WRITE_ACTIONS = ("create", "update", "delete")


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _matrix_pairs(matrix):
    pairs = set()
    for resource, actions in _as_dict(matrix).items():
        for action, value in _as_dict(actions).items():
            if value is True:
                pairs.add((resource, action))
    return pairs


def extra_role_assignments(user):
    """Extra roles the user holds in the current business and that are still assigned."""
    from django.db.models import Q
    from inventory_apps.clients.workspaces import current_client
    if not user.pk:
        return []
    client = current_client()
    scope = Q(workspace_id=client.pk) | Q(workspace_id__isnull=True) if client else Q(workspace_id__isnull=True)
    return list(user.extra_roles.filter(scope, unassigned_at__isnull=True).select_related("role"))


def active_roles(user):
    """The user's primary role followed by every extra role still assigned to them here."""
    roles = []
    if getattr(user, "role_id", None):
        roles.append(user.role)
    for assignment in extra_role_assignments(user):
        if assignment.role not in roles:
            roles.append(assignment.role)
    return roles


def disabled_modules():
    from inventory_apps.erp_base.models import TenantModule
    return set(TenantModule.objects.filter(enabled=False).values_list("key", flat=True))


def granted_pairs(user):
    """Every (resource, action) the user holds, after roles, grants, implied reads and module gates."""
    pairs = set()
    for role in active_roles(user):
        pairs |= _matrix_pairs(role.permissions)
    pairs |= _matrix_pairs(getattr(user, "permission_overrides", {}))

    # Write implies read: you cannot change what you cannot see.
    pairs |= {(resource, "read") for resource, action in pairs if action in WRITE_ACTIONS}

    # A module switched off for the tenant grants nothing, not even to owners.
    pairs = {(resource, action) for resource, action in pairs if resource not in disabled_modules()}
    return pairs


def user_can(user, resource, action):
    """True when the user may perform `action` on `resource`."""
    if user is None or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return resource not in disabled_modules()
    return (resource, action) in granted_pairs(user)


def effective_matrix(user):
    """
    The matrix the server enforces for this user. Served to the frontend so that the
    buttons it shows match what the API allows.
    """
    pairs = granted_pairs(user) if user.is_active and not user.is_superuser else None
    matrix = {}
    for resource in ALL_RESOURCES:
        matrix[resource] = {}
        for action in ALL_ACTIONS:
            if user.is_superuser:
                granted = resource not in disabled_modules()
            else:
                granted = bool(pairs) and (resource, action) in pairs
            matrix[resource][action] = granted
    return matrix


def validate_matrix(matrix):
    """
    Check the shape of a permission matrix. Returns a list of problems (empty when valid).
    Unknown resources and actions are rejected so typos cannot silently grant nothing.
    """
    problems = []
    if not isinstance(matrix, dict):
        return ["Permissions must be an object keyed by resource."]
    for resource, actions in matrix.items():
        if resource not in ALL_RESOURCES:
            problems.append(f"Unknown resource '{resource}'.")
            continue
        if not isinstance(actions, dict):
            problems.append(f"Permissions for '{resource}' must be an object keyed by action.")
            continue
        for action, value in actions.items():
            if action not in ALL_ACTIONS:
                problems.append(f"Unknown action '{action}' for '{resource}'.")
            elif not isinstance(value, bool):
                problems.append(f"'{resource}.{action}' must be true or false.")
    return problems


def grants_within(actor, grants):
    """
    Delegation rule: a user can only grant what they hold themselves.
    Returns the "resource.action" entries in `grants` the actor does not have.
    """
    held = granted_pairs(actor) if not actor.is_superuser else None
    missing = []
    for resource, actions in _as_dict(grants).items():
        for action, value in _as_dict(actions).items():
            if not value:
                continue
            if held is not None and (resource, action) not in held:
                missing.append(f"{resource}.{action}")
    return missing


def role_grants(role, resource, action):
    """Whether a role's own matrix allows the action. Used to see what an account can do, not who is asking."""
    return bool(_as_dict(_as_dict(role.permissions).get(resource)).get(action))


def role_grants_within(actor, role):
    """Assigning a role gives its whole matrix, so the same delegation rule applies."""
    return grants_within(actor, role.permissions)


def sees_all_records(user):
    """
    Record scope for list and detail views. People who run the business (settings read:
    owners and managers) see every record; everyone else sees only the records they own,
    such as the invoices they issued.
    """
    return user.is_superuser or user_can(user, "settings", "read")


def only_true(matrix):
    """Keep only the granted entries, so stored overrides stay minimal and read is implied."""
    pairs = _matrix_pairs(matrix)
    pairs |= {(resource, "read") for resource, action in pairs if action in WRITE_ACTIONS}
    result = {}
    for resource, action in sorted(pairs):
        result.setdefault(resource, {})[action] = True
    return result
