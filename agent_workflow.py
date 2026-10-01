import os
import sys
from typing import Literal, Annotated
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AnyMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from models import CatalogItem, QualityAssessment, EnrichedCatalogItem, CatalogAgentState

class AgentWorkflowState(CatalogAgentState):
    messages: Annotated[list[AnyMessage], add_messages]

async def run_orchestration(initial_state: dict) -> dict:
    # The "-u" flag is CRITICAL. It prevents Windows from buffering the JSON-RPC messages.
    mcp_client = MultiServerMCPClient({
        "catalog_server": {
            "command": sys.executable,
            "args": ["-u", "mcp_server.py"], 
            "transport": "stdio"
        }
    })
    
    mcp_tools = await mcp_client.get_tools()

    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    llm_with_tools = llm.bind_tools(mcp_tools)

    def quality_assessor_node(state: AgentWorkflowState):
        if not state.get("messages"):
            raw_item = state["raw_item"]
            prompt = f"Evaluate this catalog item: {raw_item.name}\nCategory: {raw_item.category}\nSpecs: {raw_item.specs}\nUse your tools to find the required specs for this category, then evaluate completeness."
            messages = [SystemMessage(content="You are a QA auditor."), HumanMessage(content=prompt)]
        else:
            messages = state["messages"]

        response = llm_with_tools.invoke(messages)
        
        if response.tool_calls:
            return {"messages": [response], "workflow_status": "assessing"}
        
        assessor_parser = llm.with_structured_output(QualityAssessment, strict=False)
        final_assessment = assessor_parser.invoke([HumanMessage(content=response.content)])
        return {"assessment": final_assessment, "workflow_status": "assessed", "messages": [response]}

    def enrichment_node(state: AgentWorkflowState):
        last_message = state["messages"][-1]
        
        if last_message.name != "enrichment_agent" and not getattr(last_message, "tool_calls", None):
            raw_item = state["raw_item"]
            assessment = state["assessment"]
            prompt = f"Enrich {raw_item.name} based on this QA feedback: {assessment.missing_attributes}.\nTags available: {raw_item.compatibility_tags}.\nUse tools to validate the taxonomy path and find cross-sell candidates before finalizing."
            messages = state["messages"] + [SystemMessage(content="You are a merchandiser.", name="enrichment_agent"), HumanMessage(content=prompt)]
        else:
            messages = state["messages"]

        response = llm_with_tools.invoke(messages)
        
        if response.tool_calls:
            return {"messages": [response], "workflow_status": "enriching"}
        
        enrichment_parser = llm.with_structured_output(EnrichedCatalogItem, strict=False)
        enriched_data = enrichment_parser.invoke([HumanMessage(content=response.content)])
        return {"enriched_item": enriched_data, "workflow_status": "enrichment_complete", "messages": [response]}

    def assessor_router(state: AgentWorkflowState) -> Literal["tools", "enrichment"]:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        return "enrichment"

    def enrichment_router(state: AgentWorkflowState) -> Literal["tools", "END"]:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        return "END"

    def tool_return_router(state: AgentWorkflowState) -> Literal["quality_assessor", "enrichment"]:
        if state["workflow_status"] == "assessing":
            return "quality_assessor"
        return "enrichment"

    workflow = StateGraph(AgentWorkflowState)
    workflow.add_node("quality_assessor", quality_assessor_node)
    workflow.add_node("enrichment", enrichment_node)
    workflow.add_node("tools", ToolNode(mcp_tools))

    workflow.add_edge(START, "quality_assessor")
    workflow.add_conditional_edges("quality_assessor", assessor_router, {"tools": "tools", "enrichment": "enrichment"})
    workflow.add_conditional_edges("enrichment", enrichment_router, {"tools": "tools", "END": END})
    workflow.add_conditional_edges("tools", tool_return_router, {"quality_assessor": "quality_assessor", "enrichment": "enrichment"})

    catalog_intelligence_graph = workflow.compile()
    
    # Execute natively (the library handles transport cleanup automatically in v0.1.0)
    return await catalog_intelligence_graph.ainvoke(initial_state)