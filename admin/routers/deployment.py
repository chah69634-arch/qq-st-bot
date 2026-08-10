"""Read-only deployment capability and preflight projections."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from admin.auth import require_scopes
from core.config_loader import get_config
from core.deployment_capabilities import capability_projection, deployment_mode
from core.sandbox import get_paths

router = APIRouter()


def _persistent_root_state() -> str:
    root = get_paths().root_dir()
    if not root.exists():
        return "missing"
    return "writable" if os.access(root, os.W_OK) else "read_only"


def deployment_capability_projection() -> dict:
    from channels import desktop_ws

    ack_at = desktop_ws.get_last_ack_time()
    rows = capability_projection(
        desktop_ws_online=desktop_ws.is_connected(),
        last_ack_at=ack_at,
    )
    return {
        "mode": deployment_mode(),
        "desktop_ws_online": desktop_ws.is_connected(),
        "capabilities": [
            {
                "logical_name": row.logical_name,
                "status": row.status,
                "reason": row.reason,
                "last_ack_at": row.last_ack_at,
            }
            for row in rows
        ],
    }


@router.get("/observability/deployment-capabilities", summary="Read deployment capability projection")
async def get_deployment_capabilities(_auth=Depends(require_scopes("state.read"))):
    return deployment_capability_projection()


@router.get("/system/deployment-preflight", summary="Read redacted deployment preflight")
async def get_deployment_preflight(_auth=Depends(require_scopes("state.read"))):
    cfg = get_config()
    admin_cfg = cfg.get("admin", {}) if isinstance(cfg.get("admin"), dict) else {}
    reverse_proxy = cfg.get("reverse_proxy", {})
    reverse_proxy = reverse_proxy if isinstance(reverse_proxy, dict) else {}
    mode = deployment_mode(cfg)
    capabilities = deployment_capability_projection()
    blocked = [
        row["logical_name"] for row in capabilities["capabilities"]
        if row["status"] == "disabled"
    ]
    frozen = [
        row["logical_name"] for row in capabilities["capabilities"]
        if row["status"] == "frozen"
    ]
    tls_declared = bool(cfg.get("tls") or cfg.get("https") or cfg.get("wss") or reverse_proxy.get("tls"))
    owner_id = str(cfg.get("scheduler", {}).get("owner_id", "owner"))
    return {
        "mode": mode,
        "bind": {
            "host": str(admin_cfg.get("host") or "127.0.0.1"),
            "public_listener": str(admin_cfg.get("host") or "127.0.0.1") not in {"127.0.0.1", "localhost"},
        },
        "tls_wss_declared": tls_declared,
        "persistent_data": _persistent_root_state(),
        "desktop_ws": "online" if capabilities["desktop_ws_online"] else "offline",
        "disabled_capabilities": blocked,
        "frozen_capabilities": frozen,
        "diary_sync": "configured" if get_paths().diary_mirror_status(owner_id=owner_id).exists() else "never_synced",
        "port_scan": "not_performed",
        "credentials": "redacted",
    }
