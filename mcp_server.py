import os, json
from mcp.server.fastmcp import FastMCP
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
# Prefers a read-only user if MONGO_URI_READONLY is set in .env, otherwise uses MONGO_URI
db = MongoClient(os.getenv("MONGO_URI_READONLY") or os.getenv("MONGO_URI"))["sales_db"]
mcp = FastMCP("sales-db")

BLOCKED_OPERATORS = {"$out", "$merge", "$function", "$accumulator"}
ALLOWED_COLLECTIONS = {"orders", "customers", "products"}


def _dump(data) -> str:
    return json.dumps(data, default=str, indent=2)


def _contains_blocked(obj) -> bool:
    """Scan the whole pipeline, including nested sub-pipelines."""
    if isinstance(obj, dict):
        return any(k in BLOCKED_OPERATORS or _contains_blocked(v) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_contains_blocked(x) for x in obj)
    return False


@mcp.tool()
def get_schema() -> str:
    """Return every collection with one sample document, so the model knows the data shape.
    Call this first before writing any query."""
    out = {}
    for name in db.list_collection_names():
        out[name] = db[name].find_one(projection={"_id": 0})
    return _dump(out)


@mcp.tool()
def run_aggregation(collection: str, pipeline: list[dict]) -> str:
    """Run a read-only MongoDB aggregation pipeline on 'orders', 'customers' or 'products'.
    Returns at most 50 documents. Write stages and server-side JavaScript are blocked."""
    if collection not in ALLOWED_COLLECTIONS:
        return f"Error: collection must be one of {sorted(ALLOWED_COLLECTIONS)}"
    if _contains_blocked(pipeline):
        return "Error: write stages and JavaScript operators are not allowed."
    try:
        result = list(db[collection].aggregate(pipeline + [{"$limit": 51}], maxTimeMS=10000))
        note = ""
        if len(result) > 50:
            result, note = result[:50], "\n(Result truncated to the first 50 rows.)"
        return _dump(result) + note
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
