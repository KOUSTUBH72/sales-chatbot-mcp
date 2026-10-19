import asyncio, os, sys
import streamlit as st
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import multi_agent as ma

st.set_page_config(page_title="Sales Chatbot", page_icon="📊")
st.title("📊 Superstore Sales Chatbot")
st.caption("Multi-agent (router, query, analyst, validator) over MongoDB via MCP")


def show(text):
    """Escape $ so Streamlit doesn't treat dollar amounts as math."""
    return text.replace("$", "\\$")


def root_error(e):
    """Dig the real error out of a TaskGroup / ExceptionGroup wrapper."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return e


async def answer(question):
    # fresh Gemini client for this event loop (asyncio.run makes a new loop per question)
    ma.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            decls = [types.FunctionDeclaration(
                name=t.name, description=t.description or "",
                parameters_json_schema=ma.clean(t.inputSchema)) for t in tools]
            schema = (await session.call_tool("get_schema", {})).content[0].text
            return await ma.chatbot(session, decls, schema, question)


if "history" not in st.session_state:
    st.session_state.history = []

for role, text in st.session_state.history:
    with st.chat_message(role):
        st.write(show(text))

q = st.chat_input("Ask about sales, customers, regions, categories...")
if q:
    st.session_state.history.append(("user", q))
    with st.chat_message("user"):
        st.write(show(q))
    with st.chat_message("assistant"):
        with st.spinner("Agents are working..."):
            try:
                a = asyncio.run(answer(q))
            except Exception as e:
                r = root_error(e)
                a = f"Error: {type(r).__name__}: {str(r)[:300]}"
        st.write(show(a))
    st.session_state.history.append(("assistant", a))
