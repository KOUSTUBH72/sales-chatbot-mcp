# Superstore Sales Chatbot (Multi-Agent, MCP, MongoDB)

A chatbot that answers natural-language questions about sales data stored in MongoDB.
Gemini agents call tools exposed by an MCP server, which gives controlled, read-only database access.

## Architecture

    User -> Streamlit UI -> Router agent -> Query agent -> Analyst agent -> Validator agent
                                                |
                                         MCP client (stdio)
                                                |
                                         MCP server (FastMCP) -> MongoDB Atlas

| Component | Role |
|---|---|
| `import_data.py` | Loads the Kaggle Superstore CSV into MongoDB (customers, products, orders with embedded line items) |
| `mcp_server.py` | MCP server with 7 tools: schema, read-only aggregation, and predefined sales queries |
| `multi_agent.py` | Router, Query, Analyst and Validator agents on Gemini, with retry and fallback on 503 errors |
| `app.py` | Streamlit chat UI |
| `eval.py` | 10-question evaluation with ground truth computed directly from MongoDB |

## Design decisions

- **MCP for tool access:** one server, reusable by any MCP client.
- **Guardrails:** collection allow-list, blocked `$out` and `$merge`, 50-row result limit, errors returned as text.
- **Deterministic tools for arithmetic:** the evaluation showed the LLM making sums slightly wrong, so totals are computed in the database.
- **Multi-agent trade-off:** better separation of concerns and answer checking, at the cost of more latency and requests per question.

## Evaluation

First run: 8/10. Failures: an LLM arithmetic slip (a digit off in a yearly total) and an invalid
aggregation pipeline from a lightweight model. After adding `yearly_sales` and `sales_by_category`
tools and tightening the prompt: 10/10 on the same set. The set is small and was tuned against,
so it shows the fixes work, not general accuracy.

## Setup

    pip install -r requirements.txt
    # .env needs: MONGO_URI, GEMINI_API_KEY, GEMINI_MODEL (plus optional per-agent models)
    # Download the Superstore Sales dataset from Kaggle to data/superstore.csv
    python import_data.py
    python multi_agent.py          # terminal chatbot
    streamlit run app.py           # web UI
    python eval.py 0 10            # evaluation

## Limitations

- The data has sales only: no profit, quantity or discount.
- Free-tier Gemini has small daily quotas and occasional 503 errors.
