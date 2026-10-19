import asyncio, os, re, sys, csv
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pymongo import MongoClient
import multi_agent as ma   # loads .env

ma.VALIDATE = os.getenv("EVAL_VALIDATE", "0") == "1"   # off by default to save quota
db = MongoClient(os.getenv("MONGO_URI"))["sales_db"]


def agg(coll, pipeline):
    return list(db[coll].aggregate(pipeline))


def nums(text):
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))]


def has_num(ans, v):
    return any(abs(n - v) <= 0.011 for n in nums(ans))


def has_text(ans, s):
    return str(s).lower() in ans.lower()


# ---- ground truth, straight from MongoDB (no LLM) ----
region = agg("orders", [{"$group": {"_id": "$region", "s": {"$sum": "$total_sales"}}},
                        {"$sort": {"s": -1}}, {"$limit": 1}])[0]
n_orders = db.orders.count_documents({})
n_customers = db.customers.count_documents({})
s2017 = agg("orders", [{"$match": {"$expr": {"$eq": [{"$year": "$order_date"}, 2017]}}},
                       {"$group": {"_id": None, "s": {"$sum": "$total_sales"}}}])[0]["s"]
topc = agg("orders", [{"$group": {"_id": "$customer_id", "s": {"$sum": "$total_sales"}}},
                      {"$sort": {"s": -1}}, {"$limit": 1},
                      {"$lookup": {"from": "customers", "localField": "_id",
                                   "foreignField": "_id", "as": "c"}}])[0]
topc_name = topc["c"][0]["name"]
subcat = agg("orders", [{"$unwind": "$items"},
                        {"$group": {"_id": "$items.sub_category", "s": {"$sum": "$items.sales"}}},
                        {"$sort": {"s": -1}}, {"$limit": 1}])[0]
ship = agg("orders", [{"$group": {"_id": "$ship_mode", "n": {"$sum": 1}}},
                      {"$sort": {"n": -1}}, {"$limit": 1}])[0]
tech = agg("orders", [{"$unwind": "$items"}, {"$match": {"items.category": "Technology"}},
                      {"$group": {"_id": None, "s": {"$sum": "$items.sales"}}}])[0]["s"]

TESTS = [
    ("Which region has the highest sales and how much?",
     f"{region['_id']}, {region['s']:.2f}",
     lambda a: has_text(a, region["_id"]) and has_num(a, region["s"])),
    ("How many orders are there in total?",
     str(n_orders), lambda a: has_num(a, n_orders)),
    ("What were the total sales in 2017?",
     f"{s2017:.2f}", lambda a: has_num(a, s2017)),
    ("Who is the top customer by sales and how much did they spend?",
     f"{topc_name}, {topc['s']:.2f}",
     lambda a: has_text(a, topc_name) and has_num(a, topc["s"])),
    ("Which product sub-category has the highest sales?",
     f"{subcat['_id']}, {subcat['s']:.2f}",
     lambda a: has_text(a, subcat["_id"]) and has_num(a, subcat["s"])),
    ("Which ship mode is used most often, and for how many orders?",
     f"{ship['_id']}, {ship['n']}",
     lambda a: has_text(a, ship["_id"]) and has_num(a, ship["n"])),
    ("How many customers are in the database?",
     str(n_customers), lambda a: has_num(a, n_customers)),
    ("What were the total sales of the Technology category?",
     f"{tech:.2f}", lambda a: has_num(a, tech)),
    ("What is the total profit?",
     "should say there is no profit data",
     lambda a: has_text(a, "profit") and any(w in a.lower() for w in
               ["no profit", "not ", "no ", "cannot", "doesn't", "does not", "only"])),
    ("What is the capital of France?",
     "should refuse (off-topic)", lambda a: has_text(a, "I can only answer")),
]


async def run(start, end):
    ma.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    results = []
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            decls = [types.FunctionDeclaration(
                name=t.name, description=t.description or "",
                parameters_json_schema=ma.clean(t.inputSchema)) for t in tools]
            schema = (await session.call_tool("get_schema", {})).content[0].text
            for i in range(start, min(end, len(TESTS))):
                q, expected, check = TESTS[i]
                print(f"\n[{i}] {q}\n    expected: {expected}")
                try:
                    ans = await ma.chatbot(session, decls, schema, q)
                    ok = bool(check(ans))
                except Exception as e:
                    ans, ok = f"ERROR: {str(e)[:200]}", False
                print(f"    answer:   {ans[:250].replace(chr(10), ' ')}")
                print(f"    RESULT:   {'PASS' if ok else 'FAIL'}")
                results.append((i, q, expected, ok, ans[:300].replace("\n", " ")))
                await asyncio.sleep(5)
    with open("eval_results.csv", "a", newline="") as f:
        csv.writer(f).writerows(results)
    passed = sum(r[3] for r in results)
    print(f"\nBatch score: {passed}/{len(results)}  (saved to eval_results.csv)")


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    b = int(sys.argv[2]) if len(sys.argv) > 2 else len(TESTS)
    asyncio.run(run(a, b))
