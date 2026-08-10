from sqlalchemy.orm import Session, joinedload
from uuid import UUID
from typing import List, Tuple

from app.modules.purchase_orders.models import PurchaseOrder, POItem
from app.modules.products.models import Product
from app.modules.suppliers.models import Supplier
from app.modules.warehouses.models import Warehouse
from app.modules.purchase_orders.schemas import PurchaseOrderCreate
from app.modules.inventory.service import InventoryService
from app.core.exceptions import OptiStockException, ResourceNotFoundError


class PurchaseOrderService:
    def __init__(self, db: Session):
        self.db = db
        # We import the Inventory Service to handle the cross-module communication!
        self.inventory_service = InventoryService(db)

    def get_pos(
        self, company_id: UUID, skip: int = 0, limit: int = 50, status: str = None
    ) -> Tuple[List[PurchaseOrder], int]:
        """Fetch paginated POs with eager-loaded items to prevent N+1 query performance issues."""
        query = (
            self.db.query(PurchaseOrder)
            .options(joinedload(PurchaseOrder.items))
            .filter(PurchaseOrder.company_id == company_id)
        )

        if status:
            query = query.filter(PurchaseOrder.status == status)

        total = query.count()
        pos = query.offset(skip).limit(limit).all()
        return pos, total

    def pipeline(self, company_id: UUID, limit: int = 100) -> List[dict]:
        """Purchase orders with the names and the provenance a screen needs.

        The read model for the Purchase Orders page, in the same sense as
        InsightsService.recommendations: the ORM response returns supplier_id
        and product_id, and a page that renders raw UUIDs at a stock controller
        is not a page. Names are joined here, once, rather than reassembled from
        four more requests in the browser.

        Provenance is the part that does not exist anywhere else. Some of these
        orders began as an assistant proposal that a human amended and approved,
        and the screen says so -- including what the model asked for when that
        differs from what was signed. Without it, an approved suggestion becomes
        an anonymous order and the whole human-in-the-loop story disappears at
        the last step.
        """
        # Imported inside the method because the dependency runs the other way
        # at import time: assistant.actions imports this service to execute an
        # approval. Same lazy-import reason as assistant.tools.
        from app.modules.assistant.models import AssistantAction

        orders = (
            self.db.query(PurchaseOrder)
            .options(joinedload(PurchaseOrder.items))
            .filter(PurchaseOrder.company_id == company_id)
            .order_by(PurchaseOrder.created_at.desc())
            .limit(limit)
            .all()
        )
        if not orders:
            return []

        order_ids = [po.id for po in orders]

        suppliers = dict(
            self.db.query(Supplier.id, Supplier.name)
            .filter(Supplier.company_id == company_id)
            .all()
        )
        warehouses = dict(
            self.db.query(Warehouse.id, Warehouse.name)
            .filter(Warehouse.company_id == company_id)
            .all()
        )
        products = {
            row.id: (row.sku, row.name)
            for row in self.db.query(Product.id, Product.sku, Product.name)
            .filter(Product.company_id == company_id)
            .all()
        }

        # One query for every order's provenance, keyed by the order it became.
        origins = {
            action.result_id: action
            for action in self.db.query(AssistantAction)
            .filter(
                AssistantAction.company_id == company_id,
                AssistantAction.result_id.in_(order_ids),
            )
            .all()
        }

        results = []
        for po in orders:
            action = origins.get(po.id)
            proposed = (action.proposed_payload or {}) if action else {}
            executed = (action.executed_payload or {}) if action else {}

            results.append(
                {
                    "id": str(po.id),
                    "status": po.status,
                    "created_at": po.created_at,
                    "expected_delivery_date": po.expected_delivery_date,
                    "total_amount": float(po.total_amount or 0),
                    "supplier_name": suppliers.get(po.supplier_id, "Unknown supplier"),
                    "warehouse_name": warehouses.get(
                        po.destination_warehouse_id, "Unknown warehouse"
                    ),
                    "items": [
                        {
                            "sku": products.get(item.product_id, ("?", "?"))[0],
                            "product_name": products.get(item.product_id, ("?", "?"))[1],
                            "quantity": item.quantity,
                            "unit_price": float(item.unit_price or 0),
                            "line_total": float(item.unit_price or 0) * item.quantity,
                        }
                        for item in po.items
                    ],
                    "units": sum(item.quantity for item in po.items),
                    # Null for an order somebody typed in by hand, which is the
                    # honest answer -- absence of provenance is not "human", it
                    # is "no proposal behind this".
                    "origin": (
                        {
                            "model": action.proposed_by_model,
                            "rationale": action.rationale,
                            "source_question": action.source_question,
                            "decided_at": action.decided_at,
                            "proposed_quantity": proposed.get("quantity"),
                            "executed_quantity": executed.get("quantity"),
                            "amended": (
                                executed.get("quantity") != proposed.get("quantity")
                            ),
                        }
                        if action
                        else None
                    ),
                }
            )
        return results

    def get_po_by_id(self, po_id: UUID, company_id: UUID) -> PurchaseOrder:
        po = (
            self.db.query(PurchaseOrder)
            .options(joinedload(PurchaseOrder.items))
            .filter(PurchaseOrder.id == po_id, PurchaseOrder.company_id == company_id)
            .first()
        )
        if not po:
            raise ResourceNotFoundError("PurchaseOrder", str(po_id))
        return po

    def create_po(self, po_in: PurchaseOrderCreate, company_id: UUID) -> PurchaseOrder:
        """Create a PO and its items in a single transaction."""
        try:
            supplier = (
                self.db.query(Supplier)
                .filter(
                    Supplier.id == po_in.supplier_id, Supplier.company_id == company_id
                )
                .first()
            )
            warehouse = (
                self.db.query(Warehouse)
                .filter(
                    Warehouse.id == po_in.destination_warehouse_id,
                    Warehouse.company_id == company_id,
                )
                .first()
            )
            product_count = (
                self.db.query(Product)
                .filter(
                    Product.id.in_([item.product_id for item in po_in.items]),
                    Product.company_id == company_id,
                )
                .count()
            )
            if (
                not supplier
                or not warehouse
                or product_count != len({item.product_id for item in po_in.items})
            ):
                raise OptiStockException(
                    code="INVALID_TENANT_REFERENCE",
                    message="Supplier, warehouse, and products must belong to the active company.",
                )

            total_amount = sum(item.quantity * item.unit_price for item in po_in.items)

            po = PurchaseOrder(
                company_id=company_id,
                supplier_id=po_in.supplier_id,
                destination_warehouse_id=po_in.destination_warehouse_id,
                expected_delivery_date=po_in.expected_delivery_date,
                status="draft",  # POs always start as drafts
                total_amount=total_amount,
            )
            self.db.add(po)
            self.db.flush()

            for item in po_in.items:
                po_item = POItem(
                    po_id=po.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )
                self.db.add(po_item)

            self.db.flush()
            return po

        except Exception as e:
            raise e

    def mark_po_as_delivered(self, po_id: UUID, company_id: UUID) -> PurchaseOrder:
        """
        [ALREADY EXISTED]
        Marks a PO as delivered and securely increments the inventory.
        """
        po = (
            self.db.query(PurchaseOrder)
            .filter(PurchaseOrder.id == po_id, PurchaseOrder.company_id == company_id)
            .first()
        )
        if not po:
            raise ResourceNotFoundError("PurchaseOrder", str(po_id))

        if po.status == "delivered":
            raise OptiStockException(
                code="ALREADY_DELIVERED", message="This PO has already been delivered."
            )

        items = self.db.query(POItem).filter(POItem.po_id == po_id).all()

        for item in items:
            self.inventory_service.adjust_inventory(
                product_id=item.product_id,
                warehouse_id=po.destination_warehouse_id,
                company_id=company_id,
                quantity_change=item.quantity,  # POSITIVE because we are receiving goods
                movement_type="po_delivery",
                reference_id=str(po.id),
            )

        po.status = "delivered"
        self.db.flush()

        return po
