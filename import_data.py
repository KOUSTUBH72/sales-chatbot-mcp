import os
import pandas as pd
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))["sales_db"]
PATH = os.path.expanduser("~/sales-chatbot/data/superstore.csv")

# 1. Load the CSV
try:
    df = pd.read_csv(PATH, encoding="utf-8")
except UnicodeDecodeError:
    df = pd.read_csv(PATH, encoding="latin-1")
print("Rows read:", len(df))

# 2. Clean
df["Order Date"] = pd.to_datetime(df["Order Date"], format="%d/%m/%Y")
df["Ship Date"] = pd.to_datetime(df["Ship Date"], format="%d/%m/%Y")
df["Postal Code"] = df["Postal Code"].apply(lambda x: None if pd.isna(x) else str(int(x)))
df["Sales"] = df["Sales"].astype(float)

# 3. Start fresh so the script can be re-run safely
for name in ["customers", "products", "orders", "sales_reps"]:
    db[name].drop()

# 4. Customers (one per Customer ID)
customers = [
    {"_id": r["Customer ID"], "name": r["Customer Name"], "segment": r["Segment"],
     "country": r["Country"], "city": r["City"], "state": r["State"],
     "postal_code": r["Postal Code"], "region": r["Region"]}
    for _, r in df.drop_duplicates("Customer ID").iterrows()
]
db.customers.insert_many(customers)

# 5. Products (one per Product ID)
products = [
    {"_id": r["Product ID"], "name": r["Product Name"],
     "category": r["Category"], "sub_category": r["Sub-Category"]}
    for _, r in df.drop_duplicates("Product ID").iterrows()
]
db.products.insert_many(products)

# 6. Orders with embedded line items
orders = []
for order_id, g in df.groupby("Order ID", sort=False):
    first = g.iloc[0]
    items = [
        {"row_id": int(r["Row ID"]), "product_id": r["Product ID"],
         "product_name": r["Product Name"], "category": r["Category"],
         "sub_category": r["Sub-Category"], "sales": round(float(r["Sales"]), 2)}
        for _, r in g.iterrows()
    ]
    orders.append({
        "_id": order_id,
        "order_date": first["Order Date"].to_pydatetime(),
        "ship_date": first["Ship Date"].to_pydatetime(),
        "ship_mode": first["Ship Mode"],
        "customer_id": first["Customer ID"],
        "region": first["Region"],
        "state": first["State"],
        "city": first["City"],
        "items": items,
        "total_sales": round(sum(i["sales"] for i in items), 2),
    })
db.orders.insert_many(orders)

# 7. Indexes for faster queries
db.orders.create_index("customer_id")
db.orders.create_index("order_date")
db.orders.create_index("region")

# 8. Summary
print("Import complete!")
for c in ["customers", "products", "orders"]:
    print(c, db[c].count_documents({}))
total = list(db.orders.aggregate([{"$group": {"_id": None, "t": {"$sum": "$total_sales"}}}]))
print("Total sales in DB:", round(total[0]["t"], 2))
print("Total sales in CSV:", round(df["Sales"].sum(), 2))
