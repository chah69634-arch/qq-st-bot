"""Authenticated Intiface hardware status and connection endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from admin.auth import require_scopes


router = APIRouter()


@router.get("/devices")
async def list_devices(auth=Depends(require_scopes("hardware"))):
    from core.hardware.buttplug_client import get_devices, is_connected

    return {"connected": is_connected(), "devices": get_devices()}


@router.post("/connect")
async def connect(auth=Depends(require_scopes("hardware"))):
    from core.hardware.buttplug_client import ensure_connected

    return {"success": await ensure_connected()}


@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    auth=Depends(require_scopes("hardware")),
):
    """Read-only hardware job observability; device state is never inferred here."""
    from core.hardware import jobs

    return {"jobs": jobs.list_jobs(status=status, active_only=active_only)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, auth=Depends(require_scopes("hardware"))):
    from core.hardware import jobs

    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="硬件任务不存在")
    return job


@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str, auth=Depends(require_scopes("hardware"))):
    from core.hardware import jobs

    job = await jobs.cancel_job(job_id, reason="admin")
    if job is None:
        raise HTTPException(status_code=404, detail="硬件任务不存在")
    return job


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, auth=Depends(require_scopes("hardware"))):
    """Compatibility alias for clients that call cancellation explicitly."""
    return await stop_job(job_id, auth=auth)
