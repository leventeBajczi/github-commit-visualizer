import requests
import datetime
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

# ---------------------- CONFIG ----------------------
GITHUB_API = "https://api.github.com"

# ---------------------- HELPERS ----------------------
def get_org_repos(org, headers):
    repos = []
    page = 1
    while True:
        url = f"{GITHUB_API}/orgs/{org}/repos?page={page}&per_page=100"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            st.error(f"Failed to fetch repos: {r.text}")
            return []
        data = r.json()
        if not data:
            break
        repos.extend([repo['name'] for repo in data])
        page += 1
    return repos


@st.cache_data(show_spinner=False)
def fetch_commits(org, repo, headers):
    since = (datetime.datetime.utcnow() - datetime.timedelta(days=60)).isoformat() + "Z"
    commits = []

    # First, get all branches
    branches = []
    page = 1
    while True:
        url = f"{GITHUB_API}/repos/{org}/{repo}/branches"
        params = {"per_page": 100, "page": page}
        r = requests.get(url, headers=headers, params=params)

        if r.status_code != 200:
            st.error(f"Failed to fetch branches: {r.text}")
            return []

        data = r.json()
        if not data:
            break

        branches.extend([b["name"] for b in data])
        page += 1

    seen_shas = set()

    # Fetch commits for each branch
    for branch in branches:
        page = 1
        while True:
            url = f"{GITHUB_API}/repos/{org}/{repo}/commits"
            params = {
                "since": since,
                "per_page": 100,
                "page": page,
                "sha": branch
            }

            r = requests.get(url, headers=headers, params=params)

            if r.status_code != 200:
                st.error(f"Failed to fetch commits for branch {branch}: {r.text}")
                break

            data = r.json()
            if not data:
                break

            for c in data:
                sha = c.get("sha")
                if sha not in seen_shas:
                    seen_shas.add(sha)
                    commits.append(c)

            page += 1

    return commits


def process_commits(commits):
    rows = []
    for c in commits:
        commit = c.get("commit", {})
        author = commit.get("author", {})
        name = author.get("name", "Unknown")
        date = author.get("date", None)

        if date:
            dt = datetime.datetime.fromisoformat(date.replace("Z", "+00:00"))
            rows.append({"date": dt.date(), "author": name})

    df = pd.DataFrame(rows)
    return df


@st.cache_data(show_spinner=False)
def fetch_commits_since_year_start(org, repo, headers):
    year = datetime.date.today().year
    since = datetime.datetime(year, 1, 1).isoformat() + "Z"
    commits = []

    branches = []
    page = 1
    while True:
        url = f"{GITHUB_API}/repos/{org}/{repo}/branches"
        params = {"per_page": 100, "page": page}
        r = requests.get(url, headers=headers, params=params)
        if r.status_code != 200:
            return []
        data = r.json()
        if not data:
            break
        branches.extend([b["name"] for b in data])
        page += 1

    seen_shas = set()
    for branch in branches:
        page = 1
        while True:
            url = f"{GITHUB_API}/repos/{org}/{repo}/commits"
            params = {"since": since, "per_page": 100, "page": page, "sha": branch}
            r = requests.get(url, headers=headers, params=params)
            if r.status_code != 200:
                break
            data = r.json()
            if not data:
                break
            for c in data:
                sha = c.get("sha")
                if sha not in seen_shas:
                    seen_shas.add(sha)
                    commits.append(c)
            page += 1

    return commits


def build_team_chart(df, repo_name):
    """Return a compact weekly-aggregated stacked bar chart for a team."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["week"] = df["date"].dt.to_period("W").apply(lambda p: p.start_time.date())
    grouped = df.groupby(["week", "author"]).size().reset_index(name="count")
    pivot = grouped.pivot(index="week", columns="author", values="count").fillna(0)

    fig, ax = plt.subplots(figsize=(4, 3))
    pivot.plot(kind="bar", stacked=True, ax=ax, legend=True)
    ax.set_title(repo_name, fontsize=9)
    ax.set_xlabel("")
    ax.set_ylabel("Commits")
    week_labels = [str(w) for w in pivot.index]
    ax.set_xticklabels(week_labels, rotation=60, ha="right", fontsize=6)
    ax.legend(fontsize=6, loc="upper left")
    plt.tight_layout()
    return fig


# ---------------------- UI ----------------------
st.title("GitHub Commit Frequency Visualizer")

# Persist PAT and org locally using Streamlit session state
if "pat" not in st.session_state:
    st.session_state.pat = ""
if "org" not in st.session_state:
    st.session_state.org = ""

pat = st.text_input("GitHub Personal Access Token", type="password", value=st.session_state.pat)
org = st.text_input("Organization name", value=st.session_state.org)

# Save to session state (local to client session)
st.session_state.pat = pat
st.session_state.org = org

if pat and org:
    headers = {"Authorization": f"token {pat}"}

    repos = get_org_repos(org, headers)

    if repos:
        tab_browser, tab_overview = st.tabs(["Commit Browser", "Team Overview"])

        # ---- Commit Browser tab ----
        with tab_browser:
            repo = st.selectbox("Select repository", repos)

            if st.button("Refresh data"):
                fetch_commits.clear()

            if repo:
                commits = fetch_commits(org, repo, headers)
                df = process_commits(commits)

                if not df.empty:
                    grouped = df.groupby(["date", "author"]).size().reset_index(name="count")
                    pivot = grouped.pivot(index="date", columns="author", values="count").fillna(0)

                    st.subheader("Commit frequency (per author)")

                    fig, ax = plt.subplots()
                    pivot.plot(kind="bar", stacked=True, ax=ax)
                    plt.xticks(rotation=45)
                    plt.tight_layout()
                    st.pyplot(fig)

                    st.subheader("Raw data")
                    st.dataframe(grouped)
                else:
                    st.info("No commits in the last 2 months.")

        # ---- Team Overview tab ----
        with tab_overview:
            current_year = str(datetime.date.today().year)
            year_repos = sorted([r for r in repos if r.startswith(current_year)])

            st.subheader(f"All {current_year} team repositories ({len(year_repos)} found)")

            if st.button("Refresh team data"):
                fetch_commits_since_year_start.clear()

            if not year_repos:
                st.info(f"No repositories found with the prefix '{current_year}'.")
            else:
                COLS = 3
                for row_start in range(0, len(year_repos), COLS):
                    row_repos = year_repos[row_start:row_start + COLS]
                    cols = st.columns(COLS)
                    for col, team_repo in zip(cols, row_repos):
                        with col:
                            st.markdown(f"**{team_repo}**")
                            with st.spinner(f"Loading {team_repo}..."):
                                team_commits = fetch_commits_since_year_start(org, team_repo, headers)
                            team_df = process_commits(team_commits)
                            if not team_df.empty:
                                fig = build_team_chart(team_df, team_repo)
                                st.pyplot(fig)
                                plt.close(fig)
                            else:
                                st.caption("No commits this year.")
    else:
        st.info("No repositories found.")
else:
    st.info("Enter PAT and organization to begin.")
