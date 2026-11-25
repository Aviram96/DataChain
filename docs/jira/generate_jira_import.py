"""Generate Jira CSV import files from ROADMAP.md."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP = REPO_ROOT / "ROADMAP.md"
OUTPUT_DIR = Path(__file__).resolve().parent

EPIC_RE = re.compile(r"^## (Epic \d+:[^\n]+)\n\n\*\*Goal\*\*: ([^\n]+)", re.MULTILINE)
STORY_RE = re.compile(
    r"^\| (US-[\d.]+)\s*\| ([^|]+?)\s*\|(?: ([^|]+?)\s*\|)?\s*$",
    re.MULTILINE,
)

MILESTONE_BY_EPIC = {
    1: "M1 - Foundation",
    2: "M1 - Foundation",
    3: "M2 - Product shell",
    4: "M2 - Product shell",
    5: "M3 - Pipeline",
    6: "M3 - Pipeline",
    7: "M4 - User value",
    8: "M4 - User value",
    9: "M5 - Hardening",
    10: "M6 - Academic",
}


@dataclass
class Epic:
    number: int
    title: str
    goal: str


@dataclass
class Story:
    story_id: str
    description: str
    status: str
    epic: Epic


def parse_roadmap(text: str) -> tuple[list[Epic], list[Story]]:
    epics: list[Epic] = []
    stories: list[Story] = []

    epic_matches = list(EPIC_RE.finditer(text))
    for index, match in enumerate(epic_matches):
        title = match.group(1).strip()
        goal = match.group(2).strip()
        epic_number = int(re.search(r"Epic (\d+)", title).group(1))
        epic = Epic(number=epic_number, title=title, goal=goal)
        epics.append(epic)

        section_start = match.end()
        section_end = epic_matches[index + 1].start() if index + 1 < len(epic_matches) else len(text)
        section = text[section_start:section_end]

        for story_match in STORY_RE.finditer(section):
            story_id = story_match.group(1).strip()
            description = story_match.group(2).strip()
            status = (story_match.group(3) or "To Do").strip()
            if status.lower().startswith("done"):
                status = "Done"
            else:
                status = "To Do"
            stories.append(
                Story(
                    story_id=story_id,
                    description=description,
                    status=status,
                    epic=epic,
                )
            )

    return epics, stories


def short_summary(story_id: str, description: str, max_len: int = 200) -> str:
    prefix = f"{story_id} "
    remaining = max_len - len(prefix)
    if len(description) <= remaining:
        return prefix + description
    trimmed = description[: remaining - 3].rstrip()
    return prefix + trimmed + "..."


def story_description(story: Story) -> str:
    milestone = MILESTONE_BY_EPIC[story.epic.number]
    return (
        f"{story.description}\n\n"
        f"Roadmap ID: {story.story_id}\n"
        f"Epic: {story.epic.title}\n"
        f"Milestone: {milestone}\n"
        f"Repository status: {story.status}"
    )


def jira_status(story: Story) -> str:
    return "Done" if story.status == "Done" else "To Do"


def write_csv(path: Path, epics: list[Epic], stories: list[Story]) -> None:
    fieldnames = [
        "Issue Type",
        "Summary",
        "Description",
        "Epic Name",
        "Status",
        "Labels",
        "Priority",
    ]

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for epic in epics:
            writer.writerow(
                {
                    "Issue Type": "Epic",
                    "Summary": epic.title,
                    "Description": f"Goal: {epic.goal}\n\nMilestone: {MILESTONE_BY_EPIC[epic.number]}",
                    "Epic Name": "",
                    "Status": "To Do",
                    "Labels": "datachain",
                    "Priority": "Medium",
                }
            )

        for story in stories:
            writer.writerow(
                {
                    "Issue Type": "Story",
                    "Summary": short_summary(story.story_id, story.description),
                    "Description": story_description(story),
                    "Epic Name": story.epic.title,
                    "Status": jira_status(story),
                    "Labels": f"datachain;{MILESTONE_BY_EPIC[story.epic.number].replace(' ', '').replace('-', '')}",
                    "Priority": "Medium",
                }
            )


def main() -> None:
    text = ROADMAP.read_text(encoding="utf-8")
    epics, stories = parse_roadmap(text)

    output = OUTPUT_DIR / "datachain-jira-import.csv"
    write_csv(output, epics, stories)

    print(f"Epics: {len(epics)}")
    print(f"Stories: {len(stories)}")
    print(f"Total issues: {len(epics) + len(stories)}")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
