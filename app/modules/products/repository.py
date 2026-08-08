from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Optional, Tuple
from app.modules.products.models import Product
from app.modules.products.schemas import ProductCreate, ProductUpdate


class ProductRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, product_id: UUID, company_id: UUID) -> Optional[Product]:
        return (
            self.db.query(Product)
            .filter(Product.id == product_id, Product.company_id == company_id)
            .first()
        )

    def get_by_sku(self, sku: str, company_id: UUID) -> Optional[Product]:
        # SKUs are only unique per company. Two different companies can have a "MUG-01"
        return (
            self.db.query(Product)
            .filter(Product.sku == sku, Product.company_id == company_id)
            .first()
        )

    def list_by_company(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
        abc_class: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Tuple[List[Product], int]:
        """Filtering happens here, in SQL, not in the client.

        The endpoint caps a page at 100 rows, so a client filtering the page it
        already holds would be searching a truncated catalogue and reporting
        confidently wrong counts. Filter first, paginate the result.
        """
        query = self.db.query(Product).filter(Product.company_id == company_id)

        if search:
            pattern = f"%{search}%"
            query = query.filter(
                Product.sku.ilike(pattern) | Product.name.ilike(pattern)
            )
        if abc_class:
            query = query.filter(Product.abc_class == abc_class.upper())
        if status:
            query = query.filter(Product.status == status)

        total = query.count()
        products = query.order_by(Product.sku).offset(skip).limit(limit).all()
        return products, total

    def create(self, product_in: ProductCreate, company_id: UUID) -> Product:
        # Tenant identity comes from the authenticated user, never the request body.
        db_product = Product(**product_in.model_dump(), company_id=company_id)
        self.db.add(db_product)
        self.db.flush()
        return db_product

    def update(self, db_product: Product, product_in: ProductUpdate) -> Product:
        # exclude_unset=True ensures we only update fields the user actually provided
        update_data = product_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_product, field, value)

        self.db.flush()
        return db_product
