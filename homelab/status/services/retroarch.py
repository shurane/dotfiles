"""RetroArch WebDAV shares directory listing health check."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import httpx

from models import HealthStatus, ServiceResult, StatusContext


async def check_retroarch(ctx: StatusContext) -> ServiceResult:
    service_id = "retroarch"
    name = "RetroArch (WebDAV)"
    container = "homelab-rclone-retroarch-1"
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(base_url=ctx.base_url("retroarch"), timeout=ctx.http_timeout) as client:
            res = await client.request("PROPFIND", "/", headers={"Depth": "1"})
            if res.status_code != 207:
                elapsed = (time.perf_counter() - t0) * 1000
                return ServiceResult(
                    service_id=service_id,
                    name=name,
                    container=container,
                    status=HealthStatus.UNHEALTHY,
                    latency_ms=elapsed,
                    summary=f"WebDAV PROPFIND failed: HTTP {res.status_code}",
                    branches=[f"[bold red]✖ WebDAV PROPFIND failed (HTTP {res.status_code})[/bold red]"],
                    error=res.text,
                )

            elapsed = (time.perf_counter() - t0) * 1000
            root = ET.fromstring(res.text)
            entries = []
            for resp in root.findall("{DAV:}response"):
                href_elem = resp.find("{DAV:}href")
                if href_elem is None or not href_elem.text:
                    continue
                href = href_elem.text
                if href in ("/", ""):
                    continue

                resourcetype = resp.find(".//{DAV:}resourcetype")
                is_dir = resourcetype is not None and resourcetype.find("{DAV:}collection") is not None
                clean_name = href.strip("/")
                entries.append(f"{clean_name}/" if is_dir else clean_name)

            entries.sort()
            styled_entries = [f"[bold magenta]{e}[/bold magenta]" for e in entries]
            summary = f"{len(entries)} shares/entries: {', '.join(entries)}"
            branches = [f"📁 WebDAV Shares: [bold cyan]{len(entries)}[/bold cyan] ({', '.join(styled_entries)})"]

            return ServiceResult(
                service_id=service_id,
                name=name,
                container=container,
                status=HealthStatus.HEALTHY,
                latency_ms=elapsed,
                summary=summary,
                branches=branches,
                raw_data={"entries": entries},
            )
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return ServiceResult(
            service_id=service_id,
            name=name,
            container=container,
            status=HealthStatus.UNHEALTHY,
            latency_ms=elapsed,
            summary=f"Error: {exc}",
            branches=[f"[bold red]✖ Error: {exc}[/bold red]"],
            error=str(exc),
        )
