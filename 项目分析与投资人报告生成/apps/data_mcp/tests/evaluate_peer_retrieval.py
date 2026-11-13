"""Live retrieval smoke cases. Run explicitly; requires configured embedding service.

These cases verify contract/status, NOT business relevance or production quality.
"""

from __future__ import annotations

import json

from data_mcp.features.listed_peer_match.service import match_listed_peers
from data_mcp.mcp.responses import adapt_listed_peers
from data_mcp.mcp.schemas import validate_tool_output

if __name__ == "__main__":
    cases = [
        (["半导体"], "该公司开发火箭"),
        (["金融"], "面向小微的数字化信贷"),
        (["半导体"], ""),
    ]
    for tags, summary in cases:
        result = match_listed_peers(tags, summary, env="dev")
        envelope = adapt_listed_peers(result)
        validate_tool_output("match_listed_peers", envelope)
        peers = envelope["data"]["peers"]
        assert all(p["assessment_status"] == "not_assessed" for p in peers)
        print(
            json.dumps(
                {
                    "query": envelope["data"]["query"],
                    "peers": [
                        {
                            "name": p["证券名称"],
                            "channels": list(p.get("retrieval_channels") or {}),
                            "status": p["assessment_status"],
                        }
                        for p in peers
                    ],
                },
                ensure_ascii=False,
            )
        )
