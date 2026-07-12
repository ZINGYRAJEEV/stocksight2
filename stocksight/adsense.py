"""
Google AdSense helpers for StockSight (earn from display ads).

Setup
-----
1. Apply at https://www.google.com/adsense/ with your public app URL
   (custom domain preferred; ``*.streamlit.app`` is often hard to get approved).
2. After approval, copy your publisher ID (``ca-pub-…``) into secrets.toml:

```toml
[adsense]
enabled = true
publisher_id = "ca-pub-XXXXXXXXXXXXXXXX"
# Optional — create a Display ad unit in AdSense and paste the data-ad-slot:
slot_banner = "1234567890"
# Auto ads (recommended while testing approval):
auto_ads = true
```

3. Host ``ads.txt`` at ``https://your-domain/ads.txt`` (see ``static/ads.txt``).
4. Restart Streamlit.

Notes
-----
- Streamlit embeds ads in an iframe via ``st.components.v1.html``.
- AdSense may reject purely iframe / Streamlit Cloud hosts — a custom domain helps.
- Keep ``enabled = false`` until you have a real publisher ID (invalid IDs waste quota).
"""

from __future__ import annotations

import html
import os
import re
from typing import Any, Optional

import streamlit as st
import streamlit.components.v1 as components

_PUB_RE = re.compile(r"^ca-pub-\d{10,20}$", re.I)


def _secrets_block() -> dict[str, Any]:
    try:
        block = st.secrets.get("adsense", {})
        if block is None:
            return {}
        return dict(block)
    except Exception:
        return {}


def load_adsense_config() -> dict[str, Any]:
    """Merge env + ``[adsense]`` secrets. Never raises."""
    block = _secrets_block()
    pub = (
        str(os.environ.get("ADSENSE_PUBLISHER_ID", "") or "").strip()
        or str(block.get("publisher_id", "") or block.get("client", "") or "").strip()
    )
    enabled_raw = os.environ.get("ADSENSE_ENABLED", "")
    if enabled_raw.strip() != "":
        enabled = enabled_raw.strip().lower() in ("1", "true", "yes", "on")
    else:
        enabled = bool(block.get("enabled", False))

    auto_ads = bool(block.get("auto_ads", True))
    slot_banner = str(block.get("slot_banner", "") or block.get("ad_slot", "") or "").strip()
    slot_sidebar = str(block.get("slot_sidebar", "") or "").strip()

    return {
        "enabled": enabled,
        "publisher_id": pub,
        "auto_ads": auto_ads,
        "slot_banner": slot_banner,
        "slot_sidebar": slot_sidebar,
        "valid_publisher": bool(_PUB_RE.match(pub)),
    }


def adsense_status_message(cfg: Optional[dict[str, Any]] = None) -> str:
    cfg = cfg or load_adsense_config()
    if not cfg["enabled"]:
        return "AdSense is off — set `[adsense] enabled = true` in secrets.toml after you get a publisher ID."
    if not cfg["publisher_id"]:
        return "AdSense enabled but `publisher_id` is missing (need `ca-pub-…`)."
    if not cfg["valid_publisher"]:
        return f"Publisher ID looks invalid: `{cfg['publisher_id']}` (expected `ca-pub-` + digits)."
    return f"AdSense on · `{cfg['publisher_id']}`"


def _inject_script_once(publisher_id: str, *, auto_ads: bool) -> None:
    if st.session_state.get("_adsense_script_injected"):
        return
    client = html.escape(publisher_id, quote=True)
    auto = "true" if auto_ads else "false"
    # components.html runs in a sandboxed iframe — still the most reliable path in Streamlit.
    components.html(
        f"""
<script async
  src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={client}"
  crossorigin="anonymous"></script>
<meta name="google-adsense-account" content="{client}">
<script>
  (window.adsbygoogle = window.adsbygoogle || []).push({{
    google_ad_client: "{client}",
    enable_page_level_ads: {auto}
  }});
</script>
<p style="font:11px/1.4 system-ui,sans-serif;color:#64748b;margin:0;">
  AdSense loader · {client}
</p>
""",
        height=28,
    )
    st.session_state["_adsense_script_injected"] = True


def render_adsense_unit(
    *,
    slot: str = "",
    format: str = "auto",
    full_width: bool = True,
    height: int = 120,
    key: str = "banner",
) -> None:
    """Render one display unit (requires publisher + slot from AdSense console)."""
    cfg = load_adsense_config()
    if not cfg["enabled"] or not cfg["valid_publisher"]:
        return
    if not slot:
        return

    client = html.escape(cfg["publisher_id"], quote=True)
    slot_esc = html.escape(slot, quote=True)
    fw = "true" if full_width else "false"
    components.html(
        f"""
<script async
  src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={client}"
  crossorigin="anonymous"></script>
<ins class="adsbygoogle"
     style="display:block"
     data-ad-client="{client}"
     data-ad-slot="{slot_esc}"
     data-ad-format="{html.escape(format, quote=True)}"
     data-full-width-responsive="{fw}"></ins>
<script>
  (adsbygoogle = window.adsbygoogle || []).push({{}});
</script>
""",
        height=height,
    )


def render_adsense_footer() -> None:
    """Footer banner — auto ads script + optional display slot."""
    cfg = load_adsense_config()
    if not cfg["enabled"]:
        return
    if not cfg["valid_publisher"]:
        st.caption(adsense_status_message(cfg))
        return

    st.markdown("---")
    st.caption("Sponsored")
    _inject_script_once(cfg["publisher_id"], auto_ads=cfg["auto_ads"])
    if cfg["slot_banner"]:
        render_adsense_unit(
            slot=cfg["slot_banner"],
            height=120,
            key="footer_banner",
        )
    else:
        st.caption(
            "Auto ads enabled. Add `slot_banner` in `[adsense]` after you create a Display unit "
            "in AdSense for a fixed footer banner."
        )


def render_adsense_sidebar() -> None:
    """Sidebar status + optional narrow unit."""
    cfg = load_adsense_config()
    with st.expander("📣 Google AdSense", expanded=False):
        st.caption(adsense_status_message(cfg))
        st.markdown(
            """
**Earn from ads** — [Apply for AdSense](https://www.google.com/adsense/) with your **public URL**,
then paste `ca-pub-…` into `.streamlit/secrets.toml` under `[adsense]`.

Prefer a **custom domain** over `*.streamlit.app` for approval. Host `ads.txt` at your site root
(see `static/ads.txt` in the repo).
"""
        )
        if cfg["enabled"] and cfg["valid_publisher"] and cfg.get("slot_sidebar"):
            render_adsense_unit(
                slot=cfg["slot_sidebar"],
                height=280,
                key="sidebar",
            )
