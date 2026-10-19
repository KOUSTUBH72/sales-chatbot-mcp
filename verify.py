import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
db = MongoClient(os.getenv("MONGO_URI"))["sales_db"]

print("Sample order:\n", db.orders.find_one(), "\n")

print("Sales by region:")
for r in db.orders.aggregate([
    {"$group": {"_id": "$region", "sales": {"$sum": "$total_sales"}, "orders": {"$sum": 1}}},
    {"$sort": {"sales": -1}}]):
    print(r)

print("\nTop 3 customers:")
for r in db.orders.aggregate([
    {"$group": {"_id": "$customer_id", "sales": {"$sum": "$total_sales"}}},
    {"$sort": {"sales": -1}}, {"$limit": 3},
    {"$lookup": {"from": "customers", "localField": "_id", "foreignField": "_id", "as": "c"}},
    {"$project": {"sales": {"$round": ["$sales", 2]}, "name": {"$first": "$c.name"}}}]):
    print(r)

print("\nSales by category:")
for r in db.orders.aggregate([
    {"$unwind": "$items"},
    {"$group": {"_id": "$items.category", "sales": {"$sum": "$items.sales"}}},
    {"$sort": {"sales": -1}}]):
    print(r)
