import os, sys, asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
BASE = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", BASE)
QUERY_MODEL = os.getenv("QUERY_MODEL", BASE)
ANALYST_MODEL = os.getenv("ANALYST_MODEL", BASE)
VALIDATOR_MODEL = os.getenv("VALIDATOR_MODEL", BASE)
FALLBACKS = [m for m in os.getenv("FALLBACK_MODELS",
             "gemini-3.1-flash-lite,gemini-3.5-flash").split(",") if m]
VALIDATE = os.getenv("VALIDATE", "1") == "1"   # set VALIDATE=0 to save quota

ROUTER_SYS = ("Classify the user's message. Reply with exactly one word: DATA if it asks about "
              "sales, orders, customers, products, regions, shipping or trends in a sales "
              "database; OTHER for anything else (greetings, general knowledge, unrelated tasks).")

QUERY_SYS = """You are the Query Agent for a Superstore sales database in MongoDB.
Your only job is to fetch the data needed to answer the question, using the tools.
- Prefer ready-made tools (sales_by_region, top_customers, monthly_sales, yearly_sales, sales_by_category) when they fit.
- Otherwise use run_aggregation with a MongoDB pipeline.
- order_date and ship_date are real dates. Use $expr with $year/$month, never date strings.
- The data has sales only: no profit, quantity or discount. Data covers 2015 to 2018.
- Orders have an 'items' array; use $unwind to analyse line items.
- If a tool result already contains what you need (for example, sum monthly figures for a yearly total), do not call another tool.
- If a tool returns an error, change the query; never repeat the same call. Pipeline stages must be real MongoDB operators such as $match, $group, $unwind.
Finish with a plain-text summary of exactly what the data shows, including the raw numbers.
Do not write a polished final answer. Never invent numbers."""

ANALYST_SYS = ("You are a sales analyst. Using ONLY the findings provided, answer the user's "
               "question clearly in 2 to 4 sentences with the key numbers. Amounts are US dollars ($). "
               "Add one short insight only if the findings support it. If the findings say the data "
               "cannot answer the question, say so plainly.")

VALIDATOR_SYS = ("You check an answer against raw tool results. Reply with exactly 'OK' if every number "
                 "and claim in the answer is supported by the tool results and the question is answered. "
                 "Otherwise reply 'FIX: ' followed by the corrected answer.")


def clean(schema):
    """Make an MCP JSON schema acceptable to Gemini."""
    if isinstance(schema, dict):
        out = {k: clean(v) for k, v in schema.items() if k != "title"}
        if out.get("type") == "array" and not out.get("items"):
            out["items"] = {"type": "object"}
        return out
    if isinstance(schema, list):
        return [clean(x) for x in schema]
    return schema


async def generate(model, contents, config):
    """Call Gemini; retry with longer waits on 503, then try backup models."""
    order = [model] * 4 + [m for m in FALLBACKS if m != model]
    for attempt, m in enumerate(order):
        try:
            return await client.aio.models.generate_content(
                model=m, contents=contents, config=config)
        except Exception as e:
            busy = "503" in str(e) or "UNAVAILABLE" in str(e)
            if not busy or attempt == len(order) - 1:
                raise
            wait = min(3 * (attempt + 1), 12)
            print(f"  [retry] {m} is busy, trying again in {wait}s")
            await asyncio.sleep(wait)


async def llm(model, system, prompt):
    """A plain agent: one request, no tools."""
    r = await generate(model, prompt, types.GenerateContentConfig(
        system_instruction=system, temperature=0))
    return (r.text or "").strip()


async def query_agent(session, declarations, schema, question, max_steps=6):
    """Tool-using agent. Returns (findings_text, tool_log)."""
    config = types.GenerateContentConfig(
        system_instruction=QUERY_SYS + "\n\nDatabase schema (sample documents):\n" + schema,
        temperature=0,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = [types.Content(role="user", parts=[types.Part(text=question)])]
    log = []
    for _ in range(max_steps):
        r = await generate(QUERY_MODEL, contents, config)
        calls = r.function_calls
        if not calls:
            return (r.text or ""), log
        contents.append(r.candidates[0].content)
        parts = []
        for c in calls:
            args = dict(c.args or {})
            print(f"  [query agent] tool: {c.name} {str(args)[:120]}")
            res = await session.call_tool(c.name, args)
            text = res.content[0].text if res.content else ""
            log.append(f"{c.name}({args}) -> {text[:5000]}")
            parts.append(types.Part.from_function_response(
                name=c.name, response={"result": text}))
        contents.append(types.Content(role="user", parts=parts))
    return "Stopped: too many tool steps.", log


async def chatbot(session, declarations, schema, q):
    route = (await llm(ROUTER_MODEL, ROUTER_SYS, q)).upper()
    print(f"  [router] {route[:10]}")
    if not route.startswith("DATA"):
        return ("I can only answer questions about the Superstore sales data "
                "(sales, orders, customers, products, regions, trends).")

    findings, log = await query_agent(session, declarations, schema, q)
    answer = await llm(ANALYST_MODEL, ANALYST_SYS, f"Question: {q}\n\nFindings:\n{findings}")
    print("  [analyst] answer drafted")

    if VALIDATE:
        verdict = await llm(
            VALIDATOR_MODEL, VALIDATOR_SYS,
            f"Question: {q}\n\nTool results:\n" + "\n".join(log) + f"\n\nAnswer:\n{answer}")
        if verdict.upper().startswith("FIX:"):
            print("  [validator] corrected the answer")
            answer = verdict[4:].strip()
        else:
            print("  [validator] OK")
    return answer


async def main():
    params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            declarations = [types.FunctionDeclaration(
                name=t.name, description=t.description or "",
                parameters_json_schema=clean(t.inputSchema)) for t in tools]
            schema = (await session.call_tool("get_schema", {})).content[0].text
            print(f"Multi-agent sales chatbot ready ({len(tools)} tools, validator "
                  f"{'on' if VALIDATE else 'off'}). Type 'exit' to quit.")
            while True:
                q = await asyncio.to_thread(input, "\nYou: ")
                if q.strip().lower() in {"exit", "quit"}:
                    break
                try:
                    print("\nBot:", await chatbot(session, declarations, schema, q))
                except Exception as e:
                    print("\nError:", str(e)[:500])


if __name__ == "__main__":
    asyncio.run(main())
