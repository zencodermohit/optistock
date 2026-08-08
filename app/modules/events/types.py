"""The event vocabulary.

One module so producers, consumers, the API and the tests all agree on the
spelling. A typo in an event name is a message that is published successfully
and consumed by nobody, which is the hardest kind of bug to see.

Names are past tense and read as facts, not commands: `stock.moved`, not
`move_stock`. An event says something happened and cannot be refused; a command
asks for something and can be. Getting that distinction wrong is how event
systems turn back into RPC with extra steps.
"""

# Stock
STOCK_MOVED = "stock.moved"
STOCK_BELOW_REORDER_POINT = "stock.below_reorder_point"
STOCK_DEPLETED = "stock.depleted"

# Sales
SALE_COMPLETED = "sale.completed"

# Hardware and external capture
SCAN_RECORDED = "scan.recorded"

ALL_EVENT_TYPES = frozenset(
    {
        STOCK_MOVED,
        STOCK_BELOW_REORDER_POINT,
        STOCK_DEPLETED,
        SALE_COMPLETED,
        SCAN_RECORDED,
    }
)

# Aggregates an event can be about.
AGGREGATE_INVENTORY = "inventory"
AGGREGATE_SALE = "sale"

# How each type is described in the UI. Kept beside the names so a new event
# type cannot be added without deciding what a human reading it would see.
EVENT_LABELS = {
    STOCK_MOVED: "Stock moved",
    STOCK_BELOW_REORDER_POINT: "Below reorder point",
    STOCK_DEPLETED: "Out of stock",
    SALE_COMPLETED: "Sale completed",
    SCAN_RECORDED: "Scan recorded",
}
