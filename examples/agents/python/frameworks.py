"""Optional wrappers. Both call the same policy-controlled PramaClient."""
def langchain_tool(client):
    from langchain_core.tools import tool
    @tool
    def prama_intelligence(requested_intent: str, query: str) -> dict:
        """Optional paid PRAMA capability; caller policy must authorize the signer."""
        return client.request(requested_intent, query)
    return prama_intelligence


def smolagents_tool(client):
    from smolagents import Tool
    class PramaIntelligence(Tool):
        name = "prama_intelligence"
        description = "Optional paid PRAMA capability under the caller's own policy."
        inputs = {"requested_intent": {"type": "string", "description": "Telegraph intent"},
                  "query": {"type": "string", "description": "Actual information need"}}
        output_type = "object"
        def forward(self, requested_intent, query):
            return client.request(requested_intent, query)
    return PramaIntelligence()
