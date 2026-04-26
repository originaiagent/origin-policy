"""Policy Gate v1 — Violation Dashboard (Streamlit)

origin-core の policy_violations テーブル / 集計ビューを読み取り、
日次推移・actor 内訳・interrupt 件数・PR インパクトを可視化する。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Policy Gate Violation Dashboard",
    page_icon=":shield:",
    layout="wide",
)

JST = ZoneInfo("Asia/Tokyo")

PERIOD_OPTIONS = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "all": None,
}


@st.cache_resource
def get_supabase_client():
    """Single Supabase client per Streamlit process."""
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL と SUPABASE_SERVICE_KEY (または SUPABASE_ANON_KEY) を環境変数に設定してください。"
        )
    return create_client(url, key)


def _fetch_paginated(
    table: str,
    *,
    time_col: str | None = None,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    client = get_supabase_client()
    rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        try:
            q = client.table(table).select("*")
            if time_col and since is not None:
                q = q.gte(time_col, since.isoformat())
            resp = q.range(offset, offset + page_size - 1).execute()
        except Exception as exc:
            raise RuntimeError(
                f"{table} の取得中にエラー (offset={offset}): {type(exc).__name__}: {exc}"
            ) from exc
        chunk = resp.data or []
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return rows


@st.cache_data(ttl=60)
def fetch_violations(period_key: str) -> pd.DataFrame:
    days = PERIOD_OPTIONS.get(period_key)
    since = datetime.now(timezone.utc) - timedelta(days=days) if days is not None else None
    rows = _fetch_paginated("policy_violations", time_col="occurred_at", since=since)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("occurred_at", "resolved_at", "created_at", "updated_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    return df


@st.cache_data(ttl=60)
def fetch_pr_impact() -> pd.DataFrame:
    rows = _fetch_paginated("v_policy_violations_pr_impact")
    return pd.DataFrame(rows)


def apply_filters(
    df: pd.DataFrame,
    tool_names: list[str],
    rule_ids: list[str],
) -> pd.DataFrame:
    if df.empty:
        return df
    out = df
    if tool_names and "tool_name" in out.columns:
        out = out[out["tool_name"].isin(tool_names)]
    if rule_ids and "rule_id" in out.columns:
        out = out[out["rule_id"].isin(rule_ids)]
    return out


def render_overview(filtered: pd.DataFrame) -> None:
    if filtered.empty:
        st.info("対象期間に違反データがありません。フィルタを緩めるか seed.sql を投入してください。")
        return

    filtered = filtered.copy()
    filtered["day"] = filtered["occurred_at"].dt.tz_convert(JST).dt.date

    total = len(filtered)
    blocked = int(filtered["blocked"].sum()) if "blocked" in filtered.columns else 0
    interrupts = int((filtered.get("resolution") == "tom_interrupt").sum())
    pending = int((filtered.get("resolution") == "pending").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("総違反", total)
    c2.metric("BLOCK 済", blocked)
    c3.metric("tom_interrupt", interrupts)
    c4.metric("pending", pending)

    left, right = st.columns(2)

    with left:
        st.subheader("① 日次違反件数 (rule_id 別)")
        daily_rule = (
            filtered.groupby(["day", "rule_id"]).size().reset_index(name="count")
        )
        fig = px.bar(daily_rule, x="day", y="count", color="rule_id", barmode="stack")
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("② actor 別違反内訳")
        actor_counts = filtered["actor"].value_counts().reset_index()
        actor_counts.columns = ["actor", "count"]
        fig = px.pie(actor_counts, names="actor", values="count", hole=0.4)
        fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    left2, right2 = st.columns(2)

    with left2:
        st.subheader("③ tom_interrupt 件数の日次推移")
        ti = filtered[filtered["resolution"] == "tom_interrupt"]
        if ti.empty:
            st.caption("tom_interrupt の記録がありません。")
        else:
            line = ti.groupby("day").size().reset_index(name="interrupts")
            fig = px.line(line, x="day", y="interrupts", markers=True)
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    with right2:
        st.subheader("⑤ rule_id 別 違反トップ 10 抜粋")
        excerpts = filtered.dropna(subset=["excerpt"]).copy()
        excerpts = excerpts.sort_values("occurred_at", ascending=False).head(10)
        cols = [c for c in ["occurred_at", "rule_id", "actor", "tool_name", "excerpt"] if c in excerpts.columns]
        st.dataframe(
            excerpts[cols],
            use_container_width=True,
            column_config={
                "excerpt": st.column_config.TextColumn(
                    "違反抜粋",
                    width="large",
                    help="違反箇所の発言抜粋（先頭 500 文字）",
                ),
            },
        )


def render_pr_impact(pr_df: pd.DataFrame, filtered_violations: pd.DataFrame) -> None:
    st.subheader("④ PR 単位の違反 → 遅延分析")
    if pr_df.empty:
        st.info("related_pr_url 付きの違反がまだありません。")
        return

    if not filtered_violations.empty and "related_pr_url" in filtered_violations.columns:
        urls = set(filtered_violations["related_pr_url"].dropna().unique().tolist())
        if urls:
            pr_df = pr_df[pr_df["related_pr_url"].isin(urls)]

    pr_df = pr_df.sort_values("total_delay_minutes", ascending=False, na_position="last")
    st.dataframe(
        pr_df,
        use_container_width=True,
        column_config={
            "related_pr_url": st.column_config.LinkColumn("PR"),
            "total_delay_minutes": st.column_config.NumberColumn("遅延 (分)"),
            "total_violations": st.column_config.NumberColumn("違反件数"),
        },
    )


def render_recent_table(filtered: pd.DataFrame) -> None:
    st.subheader("Recent Violations (直近 100 件)")
    if filtered.empty:
        st.caption("該当データなし。")
        return
    cols = [
        "occurred_at",
        "rule_id",
        "actor",
        "source",
        "tool_name",
        "blocked",
        "resolution",
        "excerpt",
        "related_pr_url",
    ]
    cols = [c for c in cols if c in filtered.columns]
    recent = filtered.sort_values("occurred_at", ascending=False).head(100)[cols]
    st.dataframe(
        recent,
        use_container_width=True,
        column_config={
            "excerpt": st.column_config.TextColumn("違反抜粋", width="large"),
            "related_pr_url": st.column_config.LinkColumn("PR"),
        },
    )


def main() -> None:
    st.title(":shield: Policy Gate Violation Dashboard")
    st.caption("origin-core / policy_violations を集計。Phase 3 Lane 4。")

    st.sidebar.header("フィルタ")
    period = st.sidebar.radio("期間", list(PERIOD_OPTIONS.keys()), index=1, horizontal=True)

    try:
        violations = fetch_violations(period)
        pr_impact = fetch_pr_impact()
    except Exception as exc:
        st.error(
            "DB 接続/クエリに失敗しました。SUPABASE_URL / SUPABASE_SERVICE_KEY を確認してください。\n"
            f"詳細: {type(exc).__name__}: {exc}"
        )
        st.stop()

    tool_choices = sorted(violations["tool_name"].dropna().unique().tolist()) if not violations.empty else []
    tools = st.sidebar.multiselect("tool_name", tool_choices, default=[])

    rule_choices = sorted(violations["rule_id"].dropna().unique().tolist()) if not violations.empty else []
    rules = st.sidebar.multiselect("rule_id", rule_choices, default=[])

    if st.sidebar.button("再読み込み"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.caption("読み取り元: origin-core / policy_violations")
    st.sidebar.caption(f"取得済 {len(violations)} 件 (server-side period filter)")

    filtered = apply_filters(violations, tools, rules)

    tab_overview, tab_pr, tab_recent = st.tabs(["Overview", "PR Impact", "Recent Violations"])
    with tab_overview:
        render_overview(filtered)
    with tab_pr:
        render_pr_impact(pr_impact, filtered)
    with tab_recent:
        render_recent_table(filtered)


if __name__ == "__main__":
    main()
