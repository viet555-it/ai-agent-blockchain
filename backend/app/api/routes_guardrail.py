from fastapi import APIRouter
from app.services.guardrail import guardrail_engine
from app.models.schemas import PolicyUpdateRequest

router = APIRouter(prefix="/guardrail", tags=["Guardrail & Security Policies"])

@router.get("/policies")
async def get_policies():
    return guardrail_engine.get_policies()

@router.post("/policies")
async def update_policies(req: PolicyUpdateRequest):
    guardrail_engine.update_policies(max_eth=req.max_eth, max_token=req.max_token)
    return {
        "status": "success",
        "message": "Cập nhật chính sách an toàn thành công",
        "current_policies": guardrail_engine.get_policies()
    }

@router.get("/audit-logs")
async def get_audit_logs():
    return {
        "count": len(guardrail_engine.audit_logs),
        "logs": guardrail_engine.get_audit_logs(limit=50)
    }

