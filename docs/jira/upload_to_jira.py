"""Bulk-create Datachain epics and stories in Jira via REST API."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

from generate_jira_import import (
    MILESTONE_BY_EPIC,
    parse_roadmap,
    short_summary,
    story_description,
    jira_status,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP = REPO_ROOT / "ROADMAP.md"


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def jira_session() -> tuple[str, str, requests.Session]:
    base_url = env("JIRA_BASE_URL").rstrip("/")
    email = env("JIRA_EMAIL")
    token = env("JIRA_API_TOKEN")
    session = requests.Session()
    session.auth = (email, token)
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    return base_url, env("JIRA_PROJECT_KEY"), session


def search_existing(session: requests.Session, base_url: str, project_key: str, roadmap_id: str) -> str | None:
    jql = (
        f'project = "{project_key}" AND description ~ "\\"{roadmap_id}\\""'
    )
    response = session.get(
        f"{base_url}/rest/api/3/search/jql",
        params={"jql": jql, "maxResults": 1, "fields": "key"},
    )
    response.raise_for_status()
    issues = response.json().get("issues", [])
    if issues:
        return issues[0]["key"]
    return None


def create_issue(
    session: requests.Session,
    base_url: str,
    project_key: str,
    issue_type: str,
    summary: str,
    description: str,
    status_name: str | None = None,
    epic_key: str | None = None,
) -> str:
    fields: dict = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }
            ],
        },
        "labels": ["datachain"],
    }

    if epic_key:
        fields["parent"] = {"key": epic_key}

    response = session.post(f"{base_url}/rest/api/3/issue", json={"fields": fields})
    if not response.ok:
        print(response.status_code, response.text, file=sys.stderr)
        response.raise_for_status()

    key = response.json()["key"]
    print(f"Created {key}: {summary}")

    if status_name and status_name != "To Do":
        transition_to_status(session, base_url, key, status_name)

    return key


def transition_to_status(session: requests.Session, base_url: str, issue_key: str, status_name: str) -> None:
    transitions = session.get(f"{base_url}/rest/api/3/issue/{issue_key}/transitions").json()["transitions"]
    for transition in transitions:
        if transition["to"]["name"].lower() == status_name.lower():
            session.post(
                f"{base_url}/rest/api/3/issue/{issue_key}/transitions",
                json={"transition": {"id": transition["id"]}},
            )
            return


def main() -> None:
    base_url, project_key, session = jira_session()
    epics, stories = parse_roadmap(ROADMAP.read_text(encoding="utf-8"))

    epic_keys: dict[str, str] = {}

    for epic in epics:
        existing = search_existing(session, base_url, project_key, f"Epic {epic.number}:")
        if existing:
            epic_keys[epic.title] = existing
            print(f"Skipping existing epic {existing}: {epic.title}")
            continue

        key = create_issue(
            session,
            base_url,
            project_key,
            issue_type="Epic",
            summary=epic.title,
            description=f"Goal: {epic.goal}\n\nMilestone: {MILESTONE_BY_EPIC[epic.number]}",
        )
        epic_keys[epic.title] = key

    for story in stories:
        existing = search_existing(session, base_url, project_key, story.story_id)
        if existing:
            print(f"Skipping existing story {existing}: {story.story_id}")
            continue

        labels_note = MILESTONE_BY_EPIC[story.epic.number]
        create_issue(
            session,
            base_url,
            project_key,
            issue_type="Story",
            summary=short_summary(story.story_id, story.description),
            description=story_description(story) + f"\nLabels note: {labels_note}",
            status_name=jira_status(story),
            epic_key=epic_keys[story.epic.title],
        )

    print("Upload complete.")


if __name__ == "__main__":
    main()
