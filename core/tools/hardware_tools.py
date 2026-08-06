"""Owner-triggered hardware actuator tools."""

from __future__ import annotations


_PATTERNS: dict[str, list[tuple[float, int]]] = {
    "gentle": [(0.3, 400), (0.0, 200), (0.3, 400), (0.0, 200), (0.4, 600)],
    "pulse": [(0.6, 200), (0.0, 150), (0.6, 200), (0.0, 150), (0.6, 200)],
    "wave": [(0.2, 300), (0.5, 300), (0.8, 300), (0.5, 300), (0.2, 300)],
    "long": [(0.5, 2000)],
}


async def toy_vibrate(
    intensity: float = 0.5,
    duration_ms: int = 1000,
    device_index: int | None = None,
) -> str:
    from core.hardware import jobs

    try:
        job, duplicate = await jobs.submit_vibration(
            device_index=device_index,
            intensity=intensity,
            duration_ms=duration_ms,
        )
    except jobs.HardwareJobConflict as exc:
        return f"已有硬件动作进行中（任务 {exc.existing_job_id[:8]}），请先停止"
    except jobs.HardwareJobError:
        return "硬件动作未受理，设备任务状态未改变"
    if duplicate:
        return f"相同硬件动作已在处理中（任务 {job['job_id'][:8]}），还剩 {job['remaining_seconds']:.0f} 秒左右"
    return f"已受理硬件动作（任务 {job['job_id'][:8]}），设备会在后台运行并到期停止"


async def toy_stop(device_index: int | None = None, job_id: str | None = None) -> str:
    from core.hardware import jobs
    from core.hardware.buttplug_client import _stop_device_command

    cancelled = await jobs.cancel_active(device_index=device_index, job_id=job_id)
    if job_id is not None and not cancelled:
        return "硬件任务不存在"
    if cancelled:
        if all(job.get("status") == "cancelled" for job in cancelled):
            return f"已取消硬件任务（{', '.join(job['job_id'][:8] for job in cancelled)}），并确认设备停止"
        if job_id is not None and cancelled[0].get("status") in jobs.TERMINAL_STATUSES:
            return f"硬件任务 {cancelled[0]['job_id'][:8]} 已结束，当前状态为 {cancelled[0]['status']}"
        return "已请求停止硬件任务，但设备停止结果不明"
    ok = await _stop_device_command(device_index=device_index)
    return "已停止" if ok else "设备未连接或操作失败"


async def toy_pattern(
    pattern_name: str = "gentle",
    device_index: int | None = None,
) -> str:
    selected = pattern_name if pattern_name in _PATTERNS else "gentle"
    from core.hardware import jobs

    try:
        job, duplicate = await jobs.submit_pattern(
            pattern_name=selected,
            steps=_PATTERNS[selected],
            device_index=device_index,
        )
    except jobs.HardwareJobConflict as exc:
        return f"已有硬件动作进行中（任务 {exc.existing_job_id[:8]}），请先停止"
    except jobs.HardwareJobError:
        return "硬件动作未受理，设备任务状态未改变"
    if duplicate:
        return f"相同的 {selected} 模式已在处理中（任务 {job['job_id'][:8]}）"
    return f"已受理 {selected} 模式（任务 {job['job_id'][:8]}），设备会在后台运行并到期停止"


async def toy_job_status(job_id: str | None = None) -> str:
    from core.hardware import jobs

    records = [jobs.get_job(job_id)] if job_id else jobs.list_jobs(active_only=True)
    records = [record for record in records if record]
    if not records:
        return "当前没有进行中的硬件动作"
    lines = []
    for record in records:
        status = record["status"]
        if status == "started":
            lines.append(f"任务 {record['job_id'][:8]} 已启动，还剩约 {record['remaining_seconds']:.0f} 秒")
        elif status == "accepted":
            lines.append(f"任务 {record['job_id'][:8]} 已受理，正在等待设备启动")
        else:
            lines.append(f"任务 {record['job_id'][:8]} 状态：{status}")
    return "；".join(lines)
