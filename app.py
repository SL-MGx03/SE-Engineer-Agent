import os
import base64
import json
import zlib
from dotenv import load_dotenv

from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from langchain.tools import tool
from langchain.messages import SystemMessage, HumanMessage, ToolMessage

from pymongo import MongoClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from typing import Annotated, Literal, TypedDict

from langgraph.graph.message import add_messages
from langgraph.graph import MessagesState, StateGraph, START, END
from langgraph.types import RetryPolicy

from IPython.display import Image, display

from prompt import prompt

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class State(TypedDict):
    messages: Annotated[list, add_messages]


def get_collection():
    client = MongoClient(os.getenv("MONGODB_URI"))
    db_name = "se_agents"
    collection_name = "se_agents"
    collection = client[db_name][collection_name]
    return collection


def get_vectorstore():
    vector_store = MongoDBAtlasVectorSearch(
        collection= get_collection(),
        embedding=embeddings,
        index_name= "vector_index"
        )
    return vector_store


@tool
def software_knowledgebase(query: str):
    """Search the Software Engineering PDF database for theories and concepts."""

    docs = get_vectorstore().similarity_search(query, k=3)
    return "\n".join([d.page_content for d in docs])


@tool
def get_uml_viewer_link(mermaid_code: str) -> str:
    """Generates a robust, clickable link to view a Mermaid UML diagram."""

    state = {
        "code": mermaid_code,
        "mermaid": {"theme": "default"},
        "updateEditor": True,
        "autoSync": True,
        "updateDiagram": True
    }

    json_state = json.dumps(state)
    data = json_state.encode('utf-8')
    base64_encoded = base64.b64encode(data).decode('utf-8')
    
    return f"https://mermaid.live/edit#base64:{base64_encoded}"


def chatbot(state: State):
    input_messages = [SystemMessage(content=prompt)] + state["messages"]
    response = llm_with_tools.invoke(input_messages)
    return {"messages": [response]}


def tool_node(state: dict):
    """Performs the tool call"""

    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
    return {"messages": result}


def should_continue(state: MessagesState) -> Literal["tool_node", END]:
    """Decide if we should continue the loop or stop based upon whether the LLM made a tool call"""

    messages = state["messages"]
    last_message = messages[-1]

    if last_message.tool_calls:
        return "tool_node"
    
    return END


def se_agent():
    agent= StateGraph(MessagesState)

    agent.add_node("chatbot", chatbot, retry=RetryPolicy(max_attempts=3))
    agent.add_node("tool_node", tool_node)

    agent.add_edge(START, "chatbot")
    agent.add_edge("tool_node", "chatbot")
    agent.add_conditional_edges(
        "chatbot",
        should_continue,
        ["tool_node",END]
    )

    agent = agent.compile()
    return agent


def show_agent(agent):
    try:
        png_bytes = agent.get_graph(xray=True).draw_mermaid_png()
        with open("agent_graph.png", "wb") as f:
            f.write(png_bytes)
            
        print("Success! Open 'agent_graph.png' in your folder to see the flow.")
    except Exception as e:
        print(f"Could not generate graph: {e}")


embeddings =GoogleGenerativeAIEmbeddings(model="gemini-embedding-2-preview", output_dimensionality=3072)
model= ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)

tools = [software_knowledgebase, get_uml_viewer_link]
tools_by_name = {tool.name: tool for tool in tools}
llm_with_tools = model.bind_tools(tools)


agent = se_agent()

#show_agent(agent)

messages = [HumanMessage(content="draw a class diagram for coca cola can machine")]
messages = agent.invoke({"messages": messages})
for m in messages["messages"]:
    m.pretty_print()
