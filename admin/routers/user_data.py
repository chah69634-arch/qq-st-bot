"""Private authored asset management for the admin panel."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from admin.auth import require_scopes
from core.data_paths import DEFAULT_CHAR_ID
from core import userdata_assets

router = APIRouter()


class DeleteAssetRequest(BaseModel):
    char_id: str = DEFAULT_CHAR_ID
    emotion: str = ""
    pack: str = ""


@router.get("/user-data/assets", summary="列出私有 authored 资产")
async def list_user_assets(category: Optional[str] = None, char_id: str = DEFAULT_CHAR_ID,
                           auth=Depends(require_scopes("persona"))):
    try:
        return {
            "assets": userdata_assets.list_assets(category=category, char_id=char_id),
            "categories": [
                {
                    "id": spec.category,
                    "label": spec.label,
                    "scope": spec.scope,
                    "desktop_available": spec.desktop_available,
                }
                for spec in userdata_assets.ASSET_SPECS.values()
            ],
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/user-data/assets", summary="安全上传私有 authored 资产")
async def upload_user_asset(
    category: str = Form(...),
    logical_id: str = Form(...),
    file: UploadFile = File(...),
    char_id: str = Form(DEFAULT_CHAR_ID),
    emotion: str = Form(""),
    pack: str = Form(""),
    replace: bool = Form(False),
    auth=Depends(require_scopes("admin")),
):
    try:
        content = await file.read(userdata_assets.MAX_PACKAGE_BYTES + 1)
        asset = userdata_assets.store_upload(
            category=category,
            logical_id=logical_id,
            filename=file.filename or "",
            content=content,
            char_id=char_id,
            emotion=emotion,
            pack=pack,
            replace=replace,
        )
        return {"asset": asset, "status": "partial" if category in {"live2d", "model3d"} else "available"}
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail={"code": "asset_exists", "logical_id": str(exc)}) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/user-data/assets/{category}/{logical_id}/impact", summary="读取资产删除影响")
async def asset_delete_impact(category: str, logical_id: str, char_id: str = DEFAULT_CHAR_ID,
                              emotion: str = "", pack: str = "",
                              auth=Depends(require_scopes("persona"))):
    try:
        return userdata_assets.deletion_impact(category=category, logical_id=logical_id, char_id=char_id,
                                               emotion=emotion, pack=pack)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/user-data/assets/{category}/{logical_id}", summary="删除私有 authored 资产")
async def delete_user_asset(category: str, logical_id: str, body: DeleteAssetRequest | None = None,
                            auth=Depends(require_scopes("admin"))):
    body = body or DeleteAssetRequest()
    try:
        result = userdata_assets.delete_asset(
            category=category,
            logical_id=logical_id,
            char_id=body.char_id,
            emotion=body.emotion,
            pack=body.pack,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "asset_bound", "message": str(exc),
                                                     "impact": userdata_assets.deletion_impact(category=category, logical_id=logical_id, char_id=body.char_id,
                                                                                                 emotion=body.emotion, pack=body.pack)}) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from admin import audit
    audit.log_event("authored_asset_deleted", label=getattr(auth, "label", None), path="/user-data/assets")
    return result
