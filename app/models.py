"""Single import point for every ORM model.

SQLAlchemy resolves relationships and foreign keys by name against a global
registry, and a name only enters that registry when its module is imported.
``app.main`` imports every router (and therefore every model) so the web process
is always complete — but a process that starts anywhere else is not.

That matters increasingly: the scheduler, the outbox relay and the event
consumers all run as their own entrypoints. Importing this module guarantees the
registry is whole regardless of where the process started, instead of failing
with ``NoReferencedTableError`` on the first query that crosses a table it has
not happened to import.

Import it for the side effect:

    import app.models  # noqa: F401
"""

from app.core.database import Base
from app.modules.alerts.models import Alert
from app.modules.analytics.models import ForecastRun
from app.modules.audit.models import AuditLog
from app.modules.companies.models import Company
from app.modules.events.models import EventOutbox
from app.modules.inventory.models import Inventory, InventoryMovement
from app.modules.products.models import Product
from app.modules.purchase_orders.models import POItem, PurchaseOrder
from app.modules.recommendations.models import Recommendation
from app.modules.reconciliation.models import Reconciliation, ReconciliationItem
from app.modules.sales.models import Customer, Sale, SaleItem
from app.modules.suppliers.models import Supplier
from app.modules.transfers.models import Transfer, TransferItem
from app.modules.users.models import User
from app.modules.warehouses.models import Warehouse

__all__ = [
    "Base",
    "Alert",
    "AuditLog",
    "Company",
    "Customer",
    "EventOutbox",
    "ForecastRun",
    "Inventory",
    "InventoryMovement",
    "POItem",
    "Product",
    "PurchaseOrder",
    "Recommendation",
    "Reconciliation",
    "ReconciliationItem",
    "Sale",
    "SaleItem",
    "Supplier",
    "Transfer",
    "TransferItem",
    "User",
    "Warehouse",
]
