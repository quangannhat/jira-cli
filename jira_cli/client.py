import requests


class JiraApiError(Exception):
    pass


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url
        self.auth = (email, api_token)
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        resp = self.session.request(method, f"{self.base_url}{path}", auth=self.auth, **kwargs)
        if not resp.ok:
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text
            raise JiraApiError(f"{method} {path} failed [{resp.status_code}]: {detail}")
        return resp

    @staticmethod
    def _adf(text: str) -> dict:
        """Wrap plain text in Atlassian Document Format, required by the v3 API."""
        return {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    def create_issue(
        self,
        project_key: str,
        summary: str,
        description: str | None = None,
        issue_type: str = "Task",
        assignee: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
    ) -> dict:
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if description:
            fields["description"] = self._adf(description)
        if assignee:
            fields["assignee"] = {"accountId": self.find_account_id(assignee)}
        if priority:
            fields["priority"] = {"name": priority}
        if labels:
            fields["labels"] = labels

        resp = self._request("POST", "/rest/api/3/issue", json={"fields": fields})
        return resp.json()

    def edit_issue(
        self,
        issue_key: str,
        summary: str | None = None,
        description: str | None = None,
        assignee: str | None = None,
        status: str | None = None,
    ) -> None:
        fields = {}
        if summary:
            fields["summary"] = summary
        if description:
            fields["description"] = self._adf(description)
        if assignee:
            fields["assignee"] = {"accountId": self.find_account_id(assignee)}

        if fields:
            self._request("PUT", f"/rest/api/3/issue/{issue_key}", json={"fields": fields})

        if status:
            self.transition_issue(issue_key, status)

    def transition_issue(self, issue_key: str, status_name: str) -> None:
        resp = self._request("GET", f"/rest/api/3/issue/{issue_key}/transitions")
        transitions = resp.json()["transitions"]
        match = next((t for t in transitions if t["name"].lower() == status_name.lower()), None)
        if not match:
            available = ", ".join(t["name"] for t in transitions)
            raise JiraApiError(f"No transition to '{status_name}'. Available: {available}")
        self._request(
            "POST", f"/rest/api/3/issue/{issue_key}/transitions", json={"transition": {"id": match["id"]}}
        )

    def find_account_id(self, query: str) -> str:
        resp = self._request("GET", "/rest/api/3/user/search", params={"query": query})
        users = resp.json()
        if not users:
            raise JiraApiError(f"No Jira user found matching '{query}'")
        return users[0]["accountId"]

    def list_assignable_users(self, project_key: str) -> list[dict]:
        resp = self._request(
            "GET",
            "/rest/api/3/user/assignable/search",
            params={"project": project_key, "maxResults": 50},
        )
        return resp.json()

    def get_issue(self, issue_key: str) -> dict:
        resp = self._request("GET", f"/rest/api/3/issue/{issue_key}")
        return resp.json()

    def search_issues(self, jql: str, max_results: int = 25) -> list[dict]:
        resp = self._request(
            "GET",
            "/rest/api/3/search",
            params={"jql": jql, "maxResults": max_results, "fields": "summary,status,assignee,issuetype"},
        )
        return resp.json()["issues"]

    def list_projects(self) -> list[dict]:
        projects = []
        start_at = 0
        while True:
            resp = self._request(
                "GET", "/rest/api/3/project/search", params={"startAt": start_at, "maxResults": 50}
            )
            page = resp.json()
            projects.extend(page["values"])
            if page.get("isLast", True):
                break
            start_at += len(page["values"])
        return projects
