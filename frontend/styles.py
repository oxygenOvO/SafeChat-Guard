"""Shared visual system for the SafeChat-Guard Streamlit product UI."""

from __future__ import annotations

import streamlit as st


GLOBAL_CSS = r"""
<style>
:root {
  --sg-navy:#10233f;
  --sg-blue:#2563d9;
  --sg-blue-soft:#edf4ff;
  --sg-bg:#f4f7fb;
  --sg-surface:#ffffff;
  --sg-line:#d9e2ef;
  --sg-ink:#18283f;
  --sg-muted:#6b7b91;
  --sg-success:#2f7d5b;
  --sg-success-soft:#edf8f2;
  --sg-warning:#b7791f;
  --sg-warning-soft:#fff7e8;
  --sg-danger:#b94a55;
  --sg-danger-soft:#fff1f2;
  --sg-purple:#6d5bd0;
  --sg-purple-soft:#f3f0ff;
  --sg-radius:12px;
  --sg-shadow:0 5px 18px rgba(16,35,63,.055);
}
html, body, [class*="css"] {
  font-family:Inter,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
}
.stApp { background:var(--sg-bg); color:var(--sg-ink); }
.main .block-container {
  max-width:1200px;
  padding:1.45rem 2rem 6rem;
}
[data-testid="stSidebar"] {
  background:#f8fafd;
  border-right:1px solid var(--sg-line);
}
[data-testid="stSidebar"] > div:first-child { padding-top:.65rem; }
[data-testid="stSidebar"] .stButton > button {
  min-height:50px;
  justify-content:flex-start;
  gap:.62rem;
  border:1px solid transparent;
  border-radius:11px;
  background:transparent;
  color:#52637a;
  font-weight:650;
  box-shadow:none;
  padding:.55rem .78rem;
}
[data-testid="stSidebar"] .stButton > button:hover {
  color:var(--sg-blue);
  border-color:#cedcf1;
  background:#f2f6fc;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
  color:#1d58bb;
  border-color:#c9dafa;
  background:var(--sg-blue-soft);
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] span {
  color:var(--sg-blue);
}
.sg-brand {
  display:flex;
  align-items:center;
  gap:.72rem;
  padding:.35rem .25rem 1rem;
}
.sg-brand-mark {
  display:grid;
  place-items:center;
  width:38px;
  height:38px;
  color:var(--sg-blue);
  background:var(--sg-blue-soft);
  border:1px solid #cbdcf7;
  border-radius:10px;
}
.sg-brand-name { color:var(--sg-navy); font-size:.95rem; font-weight:780; letter-spacing:-.01em; }
.sg-brand-meta { color:var(--sg-muted); font:600 .67rem/1.35 "IBM Plex Mono",Consolas,monospace; }
.sg-nav-label {
  color:#8794a7;
  font-size:.66rem;
  font-weight:750;
  letter-spacing:.12em;
  margin:.1rem .42rem .38rem;
}
.sg-sidebar-status {
  margin:clamp(2rem,8vh,5.5rem) .1rem .3rem;
  padding:.82rem;
  border:1px solid var(--sg-line);
  border-radius:var(--sg-radius);
  background:var(--sg-surface);
  box-shadow:0 3px 12px rgba(16,35,63,.035);
}
.sg-sidebar-status h4 { color:var(--sg-navy); font-size:.76rem; margin:0 0 .62rem; }
.sg-status-line {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:.7rem;
  padding:.3rem 0;
  color:var(--sg-muted);
  font-size:.69rem;
  border-top:1px solid #edf1f6;
}
.sg-status-line:first-of-type { border-top:0; }
.sg-status-line b { color:#3d4e65; font-weight:650; max-width:110px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.sg-dot { display:inline-block; width:7px; height:7px; margin-right:.35rem; border-radius:50%; background:#98a5b7; }
.sg-dot.success { background:var(--sg-success); box-shadow:0 0 0 3px var(--sg-success-soft); }
.sg-dot.warning { background:var(--sg-warning); }
.sg-dot.danger { background:var(--sg-danger); }
.sg-page-head {
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:2rem;
  border-bottom:1px solid var(--sg-line);
  padding:.2rem 0 1.1rem;
  margin-bottom:1.15rem;
}
.sg-kicker {
  color:var(--sg-blue);
  font:720 .68rem/1.2 "IBM Plex Mono",Consolas,monospace;
  letter-spacing:.11em;
  text-transform:uppercase;
}
.sg-page-head h1,.sg-title {
  color:var(--sg-navy);
  font-size:1.82rem;
  line-height:1.2;
  letter-spacing:-.035em;
  margin:.28rem 0 .28rem;
  font-weight:780;
}
.sg-page-head p,.sg-subtitle { color:var(--sg-muted); max-width:720px; margin:0; font-size:.9rem; }
.sg-head-meta { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:.4rem; max-width:400px; }
.sg-pill,.sg-chip {
  display:inline-flex;
  align-items:center;
  gap:.38rem;
  border:1px solid var(--sg-line);
  border-radius:999px;
  background:var(--sg-surface);
  color:#52637a;
  font-size:.7rem;
  font-weight:650;
  padding:.3rem .62rem;
  white-space:nowrap;
}
.sg-pill.success,.sg-chip.ready { border-color:#bedfce; background:var(--sg-success-soft); color:var(--sg-success); }
.sg-pill.warning { border-color:#ecd7ad; background:var(--sg-warning-soft); color:var(--sg-warning); }
.sg-pill.danger { border-color:#efc6cb; background:var(--sg-danger-soft); color:var(--sg-danger); }
.sg-pill.purple { border-color:#d8d0f8; background:var(--sg-purple-soft); color:var(--sg-purple); }
.sg-section-head { display:flex; align-items:end; justify-content:space-between; gap:1rem; margin:1.35rem 0 .62rem; }
.sg-section-head h2 { color:var(--sg-navy); font-size:.9rem; margin:0; font-weight:750; }
.sg-section-head p { color:var(--sg-muted); font-size:.72rem; margin:0; }
.sg-kpi {
  min-height:112px;
  padding:.82rem;
  border:1px solid var(--sg-line);
  border-top:3px solid var(--tone,var(--sg-blue));
  border-radius:var(--sg-radius);
  background:var(--sg-surface);
  box-shadow:var(--sg-shadow);
}
.sg-kpi-icon {
  display:grid;
  place-items:center;
  width:30px;
  height:30px;
  color:var(--tone,var(--sg-blue));
  border-radius:8px;
  background:var(--tone-soft,var(--sg-blue-soft));
  margin-bottom:.65rem;
}
.sg-kpi-label { color:var(--sg-muted); font-size:.68rem; font-weight:650; }
.sg-kpi-value { color:var(--sg-navy); font-size:1.25rem; line-height:1.25; font-weight:780; margin-top:.12rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.sg-kpi-note { color:#8a97a8; font-size:.64rem; margin-top:.2rem; }
.tone-blue { --tone:var(--sg-blue); --tone-soft:var(--sg-blue-soft); }
.tone-success { --tone:var(--sg-success); --tone-soft:var(--sg-success-soft); }
.tone-warning { --tone:var(--sg-warning); --tone-soft:var(--sg-warning-soft); }
.tone-danger { --tone:var(--sg-danger); --tone-soft:var(--sg-danger-soft); }
.tone-purple { --tone:var(--sg-purple); --tone-soft:var(--sg-purple-soft); }
.tone-neutral { --tone:#77869a; --tone-soft:#f0f3f7; }
.sg-event-table { border:1px solid var(--sg-line); border-radius:var(--sg-radius); overflow:auto; background:#fff; box-shadow:var(--sg-shadow); }
.sg-event-table table { width:100%; border-collapse:collapse; min-width:820px; font-size:.75rem; }
.sg-event-table th { padding:.66rem .72rem; text-align:left; color:#718198; background:#f8fafd; border-bottom:1px solid var(--sg-line); font-weight:700; }
.sg-event-table td { padding:.65rem .72rem; color:#3d4e65; border-bottom:1px solid #edf1f6; }
.sg-event-table tr:last-child td { border-bottom:0; }
.sg-mono { color:#617087; font-family:"IBM Plex Mono",Consolas,monospace; font-size:.69rem; }
.sg-badge { display:inline-block; border:1px solid var(--sg-line); border-radius:999px; padding:.18rem .48rem; font-size:.64rem; font-weight:750; line-height:1.2; white-space:nowrap; }
.sg-badge.pass,.sg-badge.normal,.sg-badge.none,.sg-badge.low { color:var(--sg-success); background:var(--sg-success-soft); border-color:#c5e2d3; }
.sg-badge.sanitize,.sg-badge.medium,.sg-badge.degraded { color:var(--sg-warning); background:var(--sg-warning-soft); border-color:#ecd7ad; }
.sg-badge.block,.sg-badge.high,.sg-badge.abnormal,.sg-badge.failed { color:var(--sg-danger); background:var(--sg-danger-soft); border-color:#efc6cb; }
.sg-badge.unknown,.sg-badge.not_run,.sg-badge.unloaded { color:#66768b; background:#f1f4f8; border-color:#dce3ec; }
.sg-provider-card,.sg-setting-card,.sg-about-card,.sg-health-card,.sg-info-card {
  border:1px solid var(--sg-line);
  border-radius:var(--sg-radius);
  background:var(--sg-surface);
  box-shadow:var(--sg-shadow);
}
.sg-provider-card { padding:.88rem; min-height:150px; border-top:3px solid var(--sg-purple); }
.sg-provider-head { display:flex; align-items:center; justify-content:space-between; gap:.7rem; }
.sg-provider-name { color:var(--sg-navy); font-size:.88rem; font-weight:760; }
.sg-provider-id { color:var(--sg-purple); font:650 .65rem/1.4 "IBM Plex Mono",Consolas,monospace; margin:.18rem 0 .72rem; }
.sg-provider-meta { display:grid; grid-template-columns:1fr 1fr; gap:.4rem; color:var(--sg-muted); font-size:.67rem; }
.sg-setting-card { overflow:hidden; }
.sg-setting-row { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:.78rem .9rem; border-bottom:1px solid #edf1f6; }
.sg-setting-row:last-child { border-bottom:0; }
.sg-setting-label { color:#44556c; font-size:.76rem; font-weight:650; }
.sg-setting-hint { color:#8996a8; font-size:.65rem; margin-top:.12rem; }
.sg-setting-value { color:var(--sg-navy); font:650 .7rem/1.35 "IBM Plex Mono",Consolas,monospace; text-align:right; }
.sg-about-card { padding:1.15rem; border-top:3px solid var(--sg-blue); }
.sg-about-mark { display:grid; place-items:center; width:44px; height:44px; color:var(--sg-blue); background:var(--sg-blue-soft); border-radius:11px; margin-bottom:.8rem; }
.sg-about-card h3 { color:var(--sg-navy); font-size:1.02rem; margin:0 0 .35rem; }
.sg-about-card p { color:var(--sg-muted); font-size:.75rem; line-height:1.55; margin:0 0 .75rem; }
.sg-capabilities { display:flex; flex-wrap:wrap; gap:.35rem; }
.sg-capability { border:1px solid #d7e2f2; border-radius:7px; background:#f8fafd; color:#506177; font-size:.64rem; padding:.25rem .42rem; }
.sg-info-card { display:flex; gap:.72rem; padding:.88rem 1rem; background:var(--sg-blue-soft); border-color:#ccdcf5; color:#3e5f8e; font-size:.75rem; line-height:1.5; }
.sg-health-list { border:1px solid var(--sg-line); border-radius:var(--sg-radius); background:#fff; overflow:hidden; }
.sg-health-row { display:grid; grid-template-columns:minmax(130px,1fr) minmax(90px,.55fr) minmax(200px,2fr); gap:1rem; align-items:center; padding:.72rem .85rem; border-bottom:1px solid #edf1f6; font-size:.74rem; }
.sg-health-row:last-child { border-bottom:0; }
.sg-health-row strong { color:#3c4d64; }
.sg-health-detail { color:var(--sg-muted); }
.sg-chart-title { color:var(--sg-navy); font-size:.82rem; font-weight:740; margin:.05rem 0 -.15rem; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--sg-line); border-radius:var(--sg-radius); background:var(--sg-surface); box-shadow:var(--sg-shadow); }
[data-testid="stDataFrame"] { border:1px solid var(--sg-line); border-radius:var(--sg-radius); overflow:hidden; }
[data-testid="stExpander"] { border-color:var(--sg-line); border-radius:var(--sg-radius); background:#fff; }
[data-testid="stChatMessage"] { background:#fff; border:1px solid var(--sg-line); border-radius:13px; padding:.25rem .55rem; box-shadow:0 3px 12px rgba(16,35,63,.035); }
[data-testid="stChatInput"] { border-color:#cbd8e7; }
.sg-header { border-bottom:1px solid var(--sg-line); padding:.2rem 0 1.1rem; margin-bottom:1.1rem; }
.sg-runtime { display:flex; gap:.45rem; flex-wrap:wrap; margin-top:.72rem; }
.sg-seal { border:1px solid var(--sg-line); border-left:3px solid var(--sg-success); border-radius:10px; background:#fbfdff; margin:.65rem 0 .2rem; padding:.62rem .75rem; }
.sg-seal.sanitize { border-left-color:var(--sg-warning); background:var(--sg-warning-soft); }
.sg-seal.block { border-left-color:var(--sg-danger); background:var(--sg-danger-soft); }
.sg-seal-row { display:flex; flex-wrap:wrap; gap:.45rem .9rem; color:#4d5d72; font-size:.76rem; }
.sg-seal-row b { color:var(--sg-ink); font-weight:650; }
.sg-empty { color:var(--sg-muted); text-align:center; padding:3.6rem 1rem 2.6rem; }
.sg-empty b { display:block; color:var(--sg-navy); font-size:1.08rem; margin-bottom:.35rem; }
.sg-decision-rail { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:.48rem; margin:.65rem 0 1rem; }
.sg-stage { position:relative; min-height:112px; padding:.68rem; border:1px solid var(--sg-line); border-top:3px solid var(--sg-blue); border-radius:10px; background:#fff; }
.sg-stage::after { content:""; position:absolute; right:-.5rem; top:34px; width:.5rem; border-top:1px solid #b9c8dc; }
.sg-stage:last-child::after { display:none; }
.sg-stage-index { color:var(--sg-blue); font:750 .62rem/1.2 "IBM Plex Mono",Consolas,monospace; letter-spacing:.08em; }
.sg-stage-title { color:var(--sg-navy); font-size:.74rem; font-weight:760; margin:.28rem 0; }
.sg-stage-detail { color:var(--sg-muted); font-size:.66rem; line-height:1.45; overflow-wrap:anywhere; }
.sg-stage.pass { border-top-color:var(--sg-success); }.sg-stage.sanitize { border-top-color:var(--sg-warning); }.sg-stage.block { border-top-color:var(--sg-danger); }.sg-stage.not_run { border-top-color:#98a5b7; }
.sg-score-row { display:grid; grid-template-columns:88px 1fr 52px; gap:.6rem; align-items:center; margin:.42rem 0; color:#52637a; font-size:.7rem; }
.sg-score-track { height:7px; overflow:hidden; border-radius:99px; background:#e9eef5; }
.sg-score-fill { height:100%; border-radius:99px; background:var(--sg-blue); }
.sg-policy-lock { border-left:3px solid var(--sg-warning); }
@media (max-width:900px) {
  .main .block-container { padding-left:1.2rem; padding-right:1.2rem; }
  .sg-kpi { min-height:104px; }
  .sg-decision-rail { grid-template-columns:repeat(3,minmax(0,1fr)); }
  .sg-stage::after { display:none; }
}
@media (max-width:760px) {
  .main .block-container { padding-top:.85rem; }
  .sg-page-head { display:block; }
  .sg-head-meta { justify-content:flex-start; margin-top:.8rem; }
  .sg-page-head h1,.sg-title { font-size:1.52rem; }
  [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
  [data-testid="column"] { min-width:calc(50% - .75rem); flex:1 1 calc(50% - .75rem); }
  .sg-health-row { grid-template-columns:1fr auto; gap:.45rem; }
  .sg-health-detail { grid-column:1 / -1; }
  .sg-decision-rail { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
@media (max-width:430px) {
  .main .block-container { padding:.7rem .75rem 5rem; }
  [data-testid="column"] { min-width:100%; flex-basis:100%; }
  .sg-kpi { min-height:auto; }
  .sg-page-head p { font-size:.82rem; }
  .sg-setting-row { align-items:flex-start; }
  .sg-setting-value { max-width:45%; overflow-wrap:anywhere; }
}
@media (prefers-reduced-motion:reduce) { * { scroll-behavior:auto !important; transition:none !important; } }
</style>
"""


def apply_global_styles() -> None:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
