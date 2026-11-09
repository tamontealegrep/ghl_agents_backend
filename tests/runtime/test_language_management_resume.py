from agent_runtime.targets.langgraph.graph_renderer import GraphEdge, GraphNode
from agent_runtime.runtime.graph_builder import _make_router_fn


def test_lm_resume_dynamic_goto_uses_resume_state():
    """
LM_RESUME routes via GO_TO: [resume_state]. The dynamic target must

    resolve to the state id provided in the slots (previous active state).

    Returns:
        None.
"""

    resume_target_id = "VI__VI_ASK_KNOW_SINGLE"
    target_node = GraphNode(node_id=resume_target_id, node_type="question")

    lm_resume = GraphNode(
        node_id="LM__LM_RESUME",
        node_type="message",
        route=[GraphEdge(target="[resume_state]", condition_text=None, is_mechanical=True)],
    )

    router_fn = _make_router_fn(
        lm_resume,
        node_by_id={resume_target_id: target_node},
        resolve_edges=lambda edges, ctx: edges[0].target,
    )

    # Provide resume_state in slots (captured at LM_INIT before entering LM__)
    state = {"slots": {"resume_state": resume_target_id}, "current_state": "LM__LM_RESUME", "last_user_message": "", "history": []}

    target = router_fn(state)
    assert target == resume_target_id


    
