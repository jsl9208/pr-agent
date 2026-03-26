import pytest

from pr_agent.tools.pr_similar_issue import PRSimilarIssue


@pytest.mark.asyncio
async def test_similar_issue_non_github_publishes_message(monkeypatch):
    class FakeProvider:
        def __init__(self):
            self.comments = []

        def publish_comment(self, body):
            self.comments.append(body)

    fake_provider = FakeProvider()

    class FakeSettings:
        class config:
            git_provider = "gitlab"
            publish_output = True

    monkeypatch.setattr("pr_agent.tools.pr_similar_issue.get_settings", lambda: FakeSettings)
    monkeypatch.setattr(
        "pr_agent.git_providers.get_git_provider_with_context",
        lambda _: fake_provider,
    )

    tool = PRSimilarIssue("https://gitlab.example.com/group/repo/-/merge_requests/1", None)
    result = await tool.run()

    assert result == ""
    assert fake_provider.comments == [
        "The /similar_issue tool is currently supported only for GitHub."
    ]


@pytest.mark.asyncio
async def test_similar_issue_non_github_no_publish(monkeypatch):
    class FakeSettings:
        class config:
            git_provider = "gitlab"
            publish_output = False

    monkeypatch.setattr("pr_agent.tools.pr_similar_issue.get_settings", lambda: FakeSettings)

    tool = PRSimilarIssue("https://gitlab.example.com/group/repo/-/merge_requests/1", None)
    result = await tool.run()

    assert result == ""


@pytest.mark.asyncio
async def test_similar_issue_codex_backend_is_unsupported(monkeypatch):
    class FakeSettings:
        class config:
            git_provider = "github"
            publish_output = False
            ai_handler = "codex_cli"

    monkeypatch.setattr("pr_agent.tools.pr_similar_issue.get_settings", lambda: FakeSettings)

    tool = PRSimilarIssue("https://github.com/org/repo/issues/1", None)
    result = await tool.run()

    assert result == ""
    assert "codex_cli backend" in tool.unsupported_message
