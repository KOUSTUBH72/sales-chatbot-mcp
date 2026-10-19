import os, json
from mcp.server.fastmcp import FastMCP
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))["sales_db"]
mcp = FastMCP("sales-db")

BLOCKED_STAGES = {"$out", "$merge"}
ALLOWED_COLLECTIONS = {"orders", "customers", "products"}


def _dump(data) -> str:
    return json.dumps(data, default=str, indent=2)


@mcp.tool()
def get_schema() -> str:
    """Return every collection with one sample document, so the model knows the data shape.
    Call this first before writing any query."""
    out = {}
    for name in db.list_collection_names():
        out[name] = db[name].find_one(projection={"_id": 0})
    return _dump(out)


@mcp.tool()
def run_aggregation(collection: str, pipeline: list) -> str:
    """Run a read-only MongoDB aggregation pipeline on 'orders', 'customers' or 'products'.
    Returns at most 50 documents. Write stages ($out, $merge) are blocked."""
    if collection not in ALLOWED_COLLECTIONS:
        return f"Error: collection must be one of {sorted(ALLOWED_COLLECTIONS)}"
    for stage in pipeline:
        if not isinstance(stage, dict) or BLOCKED_STAGES & set(stage.keys()):
            return "Error: write stages are not allowed."
    try:
        result = list(db[collection].aggregate(pipeline + [{"$limit": 50}]))
        return _dump(result)
    except Exception as e:
        return f"Query failed: {e}"


@mcp.tool()
def sales_by_region() -> str:
    """Total sales and number of orders for each region, highest first."""
    p = [{"$group": {"_id": "$region", "sales": {"$sum": "$total_sales"}, "orders": {"$sum": 1}}},
         {"$project": {"sales": {"$round": ["$sales", 2]}, "orders": 1}},
         {"$sort": {"sales": -1}}]
    return _dump(list(db.orders.aggregate(p)))


@mcp.tool()
def top_customers(n: int = 5) -> str:
    """Top N customers by total sales, with their names."""
    n = max(1, min(n, 50))
    p = [{"$group": {"_id": "$customer_id", "sales": {"$sum": "$total_sales"}}},
         {"$sort": {"sales": -1}}, {"$limit": n},
         {"$lookup": {"from": "customers", "localField": "_id", "foreignField": "_id", "as": "c"}},
         {"$project": {"sales": {"$round": ["$sales", 2]}, "name": {"$first": "$c.name"}}}]
    return _dump(list(db.orders.aggregate(p)))


@mcp.tool()
def monthly_sales(year: int) -> str:
    """Total sales for each month of the given year (data covers 2015 to 2018)."""
    p = [{"$match": {"$expr": {"$eq": [{"$year": "$order_date"}, year]}}},
         {"$group": {"_id": {"$month": "$order_date"}, "sales": {"$sum": "$total_sales"}}},
         {"$project": {"sales": {"$round": ["$sales", 2]}}},
         {"$sort": {"_id": 1}}]
    return _dump(list(db.orders.aggregate(p)))


@mcp.tool()
def yearly_sales(year: int) -> str:
    """Total sales and number of orders for ONE whole year (data covers 2015 to 2018).
    Use this for any 'total sales in <year>' question."""
    p = [{"$match": {"$expr": {"$eq": [{"$year": "$order_date"}, year]}}},
         {"$group": {"_id": None, "sales": {"$sum": "$total_sales"}, "orders": {"$sum": 1}}},
         {"$project": {"_id": 0, "sales": {"$round": ["$sales", 2]}, "orders": 1}}]
    return _dump({"year": year, "result": list(db.orders.aggregate(p))})


@mcp.tool()
def sales_by_category() -> str:
    """Total sales for each product category (Technology, Furniture, Office Supplies), highest first."""
    p = [{"$unwind": "$items"},
         {"$group": {"_id": "$items.category", "sales": {"$sum": "$items.sales"}}},
         {"$project": {"sales": {"$round": ["$sales", 2]}}},
         {"$sort": {"sales": -1}}]
    return _dump(list(db.orders.aggregate(p)))


if __name__ == "__main__":
    mcp.run()
