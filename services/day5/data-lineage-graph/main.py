"""
Data Lineage Graph — DPDP Compliance OS  Day 5
Real-time capture and querying of data lineage graphs in Neo4j.
Powers breach blast-radius analysis, harm scoring, and erasure verification.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import Counter, make_asgi_app
from pydantic import BaseModel, Field

log = structlog.get_logger()

app = FastAPI(title="Data Lineage Graph", version="1.0.0",
              description="Neo4j-backed real-time data lineage for breach analysis and erasure verification")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())
FastAPIInstrumentor.instrument_app(app)

NODES_REGISTERED = Counter("lineage_nodes_total", "Lineage nodes registered", ["node_type"])
EDGES_REGISTERED = Counter("lineage_edges_total", "Lineage edges registered", ["edge_type"])
BLAST_QUERIES    = Counter("lineage_blast_radius_queries_total", "Blast radius queries")


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------
class NodeType(str, Enum):
    DATA_SOURCE   = "DataSource"
    DATA_STORE    = "DataStore"
    SERVICE       = "Service"
    AI_MODEL      = "AIModel"
    THIRD_PARTY   = "ThirdParty"
    DATA_EXPORT   = "DataExport"
    PRINCIPAL     = "Principal"


class EdgeType(str, Enum):
    COLLECTS_FROM   = "COLLECTS_FROM"
    STORES_IN       = "STORES_IN"
    PROCESSED_BY    = "PROCESSED_BY"
    SHARED_WITH     = "SHARED_WITH"
    TRAINS          = "TRAINS"
    EXPORTED_TO     = "EXPORTED_TO"
    DERIVED_FROM    = "DERIVED_FROM"
    REPLICATED_TO   = "REPLICATED_TO"


class LineageNode(BaseModel):
    node_id: Optional[str] = None
    node_type: NodeType
    name: str
    system_id: str
    owner_team: str
    data_categories: list[str] = []
    contains_pii: bool = False
    contains_sensitive: bool = False
    country: str = "IN"
    metadata: dict = {}


class LineageEdge(BaseModel):
    edge_id: Optional[str] = None
    from_node_id: str
    to_node_id: str
    edge_type: EdgeType
    data_categories: list[str] = []
    volume_records_day: Optional[int] = None
    is_real_time: bool = False
    legal_basis: Optional[str] = None
    consent_required: bool = False
    metadata: dict = {}


class BlastRadiusRequest(BaseModel):
    affected_node_id: str
    max_depth: int = Field(4, ge=1, le=10)
    data_categories: list[str] = []


class BlastRadiusNode(BaseModel):
    node_id: str
    node_type: str
    name: str
    distance: int
    path: list[str]
    contains_pii: bool
    country: str
    estimated_records: Optional[int]


class BlastRadiusResponse(BaseModel):
    query_id: str
    source_node_id: str
    affected_nodes: list[BlastRadiusNode]
    total_affected: int
    cross_border_transfers: list[str]
    third_parties_affected: list[str]
    ai_models_affected: list[str]
    harm_score: int    # 0–100
    queried_at: str


# ---------------------------------------------------------------------------
# In-memory graph (replace with Neo4j driver in production)
# ---------------------------------------------------------------------------
_nodes: dict[str, dict] = {}
_edges: list[dict] = []


def compute_harm_score(affected: list[BlastRadiusNode]) -> int:
    score = 0
    score += min(40, len(affected) * 3)
    score += 20 if any(n.contains_pii for n in affected) else 0
    score += 15 if any(n.country != "IN" for n in affected) else 0
    score += 10 if any(n.node_type == NodeType.THIRD_PARTY.value for n in affected) else 0
    score += 15 if any(n.node_type == NodeType.AI_MODEL.value for n in affected) else 0
    return min(100, score)


def blast_radius(req: BlastRadiusRequest) -> BlastRadiusResponse:
    """BFS traversal of the lineage graph to find all affected downstream nodes."""
    visited: set[str] = {req.affected_node_id}
    queue: list[tuple[str, int, list[str]]] = [(req.affected_node_id, 0, [])]
    affected: list[BlastRadiusNode] = []

    while queue:
        current_id, depth, path = queue.pop(0)
        if depth >= req.max_depth:
            continue

        for edge in _edges:
            if edge["from_node_id"] == current_id:
                target_id = edge["to_node_id"]
                if target_id not in visited:
                    visited.add(target_id)
                    target_node = _nodes.get(target_id, {})
                    new_path = path + [current_id]
                    affected.append(BlastRadiusNode(
                        node_id=target_id,
                        node_type=target_node.get("node_type", "Unknown"),
                        name=target_node.get("name", "Unknown"),
                        distance=depth + 1,
                        path=new_path,
                        contains_pii=target_node.get("contains_pii", False),
                        country=target_node.get("country", "IN"),
                        estimated_records=None,
                    ))
                    queue.append((target_id, depth + 1, new_path))

    harm = compute_harm_score(affected)
    BLAST_QUERIES.inc()

    return BlastRadiusResponse(
        query_id=str(uuid.uuid4()),
        source_node_id=req.affected_node_id,
        affected_nodes=affected,
        total_affected=len(affected),
        cross_border_transfers=[n.node_id for n in affected if n.country != "IN"],
        third_parties_affected=[n.node_id for n in affected if n.node_type == NodeType.THIRD_PARTY.value],
        ai_models_affected=[n.node_id for n in affected if n.node_type == NodeType.AI_MODEL.value],
        harm_score=harm,
        queried_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "data-lineage-graph", "nodes": len(_nodes), "edges": len(_edges)}


@app.post("/lineage/nodes", status_code=201)
async def register_node(node: LineageNode):
    node_id = node.node_id or str(uuid.uuid4())
    _nodes[node_id] = {**node.model_dump(), "node_id": node_id, "registered_at": datetime.now(timezone.utc).isoformat()}
    NODES_REGISTERED.labels(node_type=node.node_type.value).inc()
    log.info("lineage.node.registered", node_id=node_id, type=node.node_type.value, name=node.name)
    return {"node_id": node_id, "status": "registered"}


@app.post("/lineage/edges", status_code=201)
async def register_edge(edge: LineageEdge):
    if edge.from_node_id not in _nodes:
        raise HTTPException(404, f"Source node {edge.from_node_id} not found")
    if edge.to_node_id not in _nodes:
        raise HTTPException(404, f"Target node {edge.to_node_id} not found")

    edge_id = edge.edge_id or str(uuid.uuid4())
    _edges.append({**edge.model_dump(), "edge_id": edge_id, "registered_at": datetime.now(timezone.utc).isoformat()})
    EDGES_REGISTERED.labels(edge_type=edge.edge_type.value).inc()
    log.info("lineage.edge.registered", edge_id=edge_id, type=edge.edge_type.value)
    return {"edge_id": edge_id, "status": "registered"}


@app.post("/lineage/blast-radius", response_model=BlastRadiusResponse)
async def compute_blast_radius(req: BlastRadiusRequest):
    """Compute breach blast radius from a compromised node."""
    if req.affected_node_id not in _nodes:
        raise HTTPException(404, f"Node {req.affected_node_id} not found in lineage graph")
    return blast_radius(req)


@app.get("/lineage/nodes/{node_id}")
async def get_node(node_id: str):
    node = _nodes.get(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    return node


@app.get("/lineage/graph/summary")
async def graph_summary():
    return {
        "node_count": len(_nodes),
        "edge_count": len(_edges),
        "nodes_with_pii": sum(1 for n in _nodes.values() if n.get("contains_pii")),
        "cross_border_nodes": sum(1 for n in _nodes.values() if n.get("country") != "IN"),
        "node_types": {t.value: sum(1 for n in _nodes.values() if n.get("node_type") == t.value) for t in NodeType},
    }


@app.get("/lineage/erasure-verification/{principal_id}")
async def verify_erasure(principal_id: str):
    """
    After erasure request: verify the principal's data has been removed
    from all nodes in the lineage graph. Returns residual data locations.
    """
    # In production: query Neo4j with MATCH (p:Principal {id: $id})-[*]->(n) RETURN n
    residual = [
        {"node_id": nid, "name": n.get("name"), "system_id": n.get("system_id")}
        for nid, n in _nodes.items()
        if principal_id in str(n.get("metadata", {}).get("principals", []))
    ]
    return {
        "principal_id": principal_id,
        "erasure_complete": len(residual) == 0,
        "residual_locations": residual,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
