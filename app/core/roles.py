"""The role vocabulary, defined once.

Before this file the same set of roles was spelled out in four places — the User
model's comment, the registration schema, the README, and various RequireRole
calls — and all four disagreed. Roles are a security boundary; when the
definition of a security boundary is scattered, "who can do what?" stops having
a reliable answer.

The platform_admin split
------------------------
platform_admin is the SaaS operator, not a customer. It is the only role that
reaches across tenants (it is what the /companies endpoints require, for
onboarding new companies). Everything else is scoped to a single company.

That is why TENANT_ASSIGNABLE_ROLES deliberately excludes it. A tenant admin
provisioning users inside their own company must not be able to mint a
platform_admin — that would be privilege escalation from "customer" to
"operator of the whole platform" via an ordinary registration call. Platform
operators are provisioned out of band, by the seed or an ops process.
"""

PLATFORM_ADMIN = "platform_admin"
ADMIN = "admin"
FINANCE = "finance"
SUPPLY_CHAIN = "supply_chain"
WAREHOUSE_MANAGER = "warehouse_manager"
SALES_REP = "sales_rep"
ANALYST = "analyst"

#: Every role the system recognises.
ALL_ROLES: tuple[str, ...] = (
    PLATFORM_ADMIN,
    ADMIN,
    FINANCE,
    SUPPLY_CHAIN,
    WAREHOUSE_MANAGER,
    SALES_REP,
    ANALYST,
)

#: Roles a tenant admin may assign within their own company.
#: Excludes PLATFORM_ADMIN on purpose — see the module docstring.
TENANT_ASSIGNABLE_ROLES: tuple[str, ...] = tuple(
    role for role in ALL_ROLES if role != PLATFORM_ADMIN
)
