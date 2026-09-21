from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from nxtrep_backend.agents.nodes import AgentGraphNodes
from nxtrep_backend.agents.state import AgentGraphState


def build_agent_execution_graph(
    nodes: AgentGraphNodes,
) -> CompiledStateGraph:
    graph = StateGraph(AgentGraphState)

    graph.add_node(
        "plan_request",
        nodes.plan_request,
    )
    graph.add_node(
        "execute_branches",
        nodes.execute_branches,
    )
    graph.add_node(
        "validate_execution",
        nodes.validate_execution,
    )
    graph.add_node(
        "synthesize_response",
        nodes.synthesize_response,
    )

    graph.add_edge(
        START,
        "plan_request",
    )
    graph.add_edge(
        "plan_request",
        "execute_branches",
    )
    graph.add_edge(
        "execute_branches",
        "validate_execution",
    )
    graph.add_edge(
        "validate_execution",
        "synthesize_response",
    )
    graph.add_edge(
        "synthesize_response",
        END,
    )

    return graph.compile()
