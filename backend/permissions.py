"""Who may do what. Routes call can() before acting; templates call it to decide which buttons to show.

    user        calculator and their own estimates only
    admin       + users list, add normal users, set password / disable / enable normal users
    superadmin  + everything else: admins, roles, deletion, activity log, everyone's estimates

Nobody can change the Super Admin account from the admin pages (it changes its own password under
Account), and nobody can create a Super Admin from the website at all.
"""

USER, ADMIN, SUPERADMIN = "user", "admin", "superadmin"
ROLE_LABELS = {USER: "User", ADMIN: "Admin", SUPERADMIN: "Super Admin"}

# Actions that apply to one target account
_MANAGE = ("reset", "disable", "enable")


def is_admin(user) -> bool:
    return bool(user) and user["role"] in (ADMIN, SUPERADMIN)


def is_superadmin(user) -> bool:
    return bool(user) and user["role"] == SUPERADMIN


def can(actor, action: str, target=None) -> bool:
    """True if `actor` may perform `action` (on the `target` account, when there is one)."""
    if not actor or not actor["is_active"]:
        return False
    role = actor["role"]

    if action in ("view_users", "add_user"):
        return role in (ADMIN, SUPERADMIN)
    if action in ("add_admin", "view_activity", "view_all_estimates", "view_user_profile"):
        return role == SUPERADMIN
    if target is None:
        return False

    self_target = actor["id"] == target["id"]
    target_role = target["role"]
    if target_role == SUPERADMIN:
        return False                     # protected, including from itself on the admin pages
    if action in _MANAGE:
        if self_target:
            return False                 # can't lock yourself out; own password is changed under Account
        return role == SUPERADMIN or (role == ADMIN and target_role == USER)
    if action == "delete":
        return role == SUPERADMIN and not self_target
    if action == "promote":
        return role == SUPERADMIN and target_role == USER
    if action == "revoke":
        return role == SUPERADMIN and target_role == ADMIN
    return False
