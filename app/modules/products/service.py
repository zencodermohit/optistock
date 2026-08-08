from uuid import UUID
from typing import List, Tuple
from sqlalchemy.orm import Session
from app.modules.products.repository import ProductRepository
from app.modules.products.schemas import ProductCreate, ProductUpdate
from app.modules.products.models import Product
from app.core.exceptions import OptiStockException, ResourceNotFoundError


class ProductService:
    def __init__(self, db: Session):
        self.repo = ProductRepository(db)

    def create_product(self, product_in: ProductCreate, company_id: UUID) -> Product:
        # Rule 1: SKUs must be unique per company
        existing = self.repo.get_by_sku(product_in.sku, company_id)
        if existing:
            raise OptiStockException(
                code="DUPLICATE_SKU",
                message=f"A product with SKU {product_in.sku} already exists.",
            )

        # Rule 2: Positive profit margin required
        if product_in.selling_price < product_in.unit_cost:
            raise OptiStockException(
                code="INVALID_PRICING",
                message="Selling price cannot be lower than unit cost.",
            )

        return self.repo.create(product_in, company_id)

    def list_products(
        self, company_id: UUID, skip: int = 0, limit: int = 100
    ) -> Tuple[List[Product], int]:
        return self.repo.list_by_company(company_id=company_id, skip=skip, limit=limit)

    def get_product(self, product_id: UUID, company_id: UUID) -> Product:
        product = self.repo.get_by_id(product_id, company_id)
        if not product:
            raise ResourceNotFoundError(resource="Product", resource_id=str(product_id))
        return product

    def update_product(
        self, product_id: UUID, product_in: ProductUpdate, company_id: UUID
    ) -> Product:
        product = self.get_product(product_id, company_id)

        # Check pricing rules combining new input and existing data
        new_sell = (
            product_in.selling_price
            if product_in.selling_price is not None
            else product.selling_price
        )
        new_cost = (
            product_in.unit_cost
            if product_in.unit_cost is not None
            else product.unit_cost
        )

        if new_sell < new_cost:
            raise OptiStockException(
                code="INVALID_PRICING",
                message="Selling price cannot be lower than unit cost.",
            )

        return self.repo.update(product, product_in)

    def delete_product(self, product_id: UUID, company_id: UUID) -> Product:
        # Rule 3: Soft deletes only. Change lifecycle state.
        product = self.get_product(product_id, company_id)
        update_schema = ProductUpdate(status="archived")
        return self.repo.update(product, update_schema)
