import os
import urllib.parse
from typing import Any

import requests


class Obsidian:
    def __init__(
        self,
        api_key: str,
        protocol: str = os.getenv("OBSIDIAN_PROTOCOL", "https").lower(),
        host: str = str(os.getenv("OBSIDIAN_HOST", "127.0.0.1")),
        port: int = int(os.getenv("OBSIDIAN_PORT", "27124")),
        verify_ssl: bool = False,
    ) -> None:
        self.api_key = api_key
        self.protocol = "http" if protocol == "http" else "https"
        self.host = host
        self.port = port
        self.verify_ssl = verify_ssl
        self.timeout = (3, 6)

    def get_base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    def _get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _safe_call(self, f: Any) -> Any:
        try:
            return f()
        except requests.HTTPError as e:
            error_data = e.response.json() if e.response.content else {}
            code = error_data.get("errorCode", -1)
            message = error_data.get("message", "<unknown>")
            raise Exception(f"Error {code}: {message}") from e
        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {str(e)}") from e

    def list_files_in_vault(self) -> Any:
        url = f"{self.get_base_url()}/vault/"

        def call_fn() -> Any:
            response = requests.get(
                url, headers=self._get_headers(), verify=self.verify_ssl, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()["files"]

        return self._safe_call(call_fn)

    def list_files_in_dir(self, dirpath: str) -> Any:
        url = f"{self.get_base_url()}/vault/{dirpath}/"

        def call_fn() -> Any:
            response = requests.get(
                url, headers=self._get_headers(), verify=self.verify_ssl, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()["files"]

        return self._safe_call(call_fn)

    def get_file_contents(self, filepath: str) -> Any:
        url = f"{self.get_base_url()}/vault/{filepath}"

        def call_fn() -> Any:
            response = requests.get(
                url, headers=self._get_headers(), verify=self.verify_ssl, timeout=self.timeout
            )
            response.raise_for_status()
            return response.text

        return self._safe_call(call_fn)

    def get_batch_file_contents(self, filepaths: list[str]) -> str:
        result = []
        for filepath in filepaths:
            try:
                content = self.get_file_contents(filepath)
                result.append(f"# {filepath}\n\n{content}\n\n---\n\n")
            except Exception as e:
                result.append(f"# {filepath}\n\nError reading file: {str(e)}\n\n---\n\n")
        return "".join(result)

    def search(self, query: str, context_length: int = 100) -> Any:
        url = f"{self.get_base_url()}/search/simple/"
        params: dict[str, str | int] = {"query": query, "contextLength": context_length}

        def call_fn() -> Any:
            response = requests.post(
                url,
                headers=self._get_headers(),
                params=params,
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        return self._safe_call(call_fn)

    def search_json(self, query: dict[str, Any]) -> Any:
        url = f"{self.get_base_url()}/search/"
        headers = self._get_headers() | {"Content-Type": "application/vnd.olrapi.jsonlogic+json"}

        def call_fn() -> Any:
            response = requests.post(
                url, headers=headers, json=query, verify=self.verify_ssl, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        return self._safe_call(call_fn)

    def append_content(self, filepath: str, content: str) -> None:
        url = f"{self.get_base_url()}/vault/{filepath}"

        def call_fn() -> None:
            response = requests.post(
                url,
                headers=self._get_headers() | {"Content-Type": "text/markdown"},
                data=content,
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()

        self._safe_call(call_fn)

    def patch_content(
        self, filepath: str, operation: str, target_type: str, target: str, content: str
    ) -> None:
        url = f"{self.get_base_url()}/vault/{filepath}"
        # Plugin expects bare block IDs; strip the leading ^ Obsidian shows in the UI
        if target_type == "block":
            target = target.lstrip("^")
        headers = self._get_headers() | {
            "Content-Type": "text/markdown",
            "Operation": operation,
            "Target-Type": target_type,
            "Target": urllib.parse.quote(target),
        }

        def call_fn() -> None:
            response = requests.patch(
                url, headers=headers, data=content, verify=self.verify_ssl, timeout=self.timeout
            )
            response.raise_for_status()

        self._safe_call(call_fn)

    def put_content(self, filepath: str, content: str) -> None:
        url = f"{self.get_base_url()}/vault/{filepath}"

        def call_fn() -> None:
            response = requests.put(
                url,
                headers=self._get_headers() | {"Content-Type": "text/markdown"},
                data=content,
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()

        self._safe_call(call_fn)

    def delete_file(self, filepath: str) -> None:
        url = f"{self.get_base_url()}/vault/{filepath}"

        def call_fn() -> None:
            response = requests.delete(
                url, headers=self._get_headers(), verify=self.verify_ssl, timeout=self.timeout
            )
            response.raise_for_status()

        self._safe_call(call_fn)

    def get_periodic_note(self, period: str, type: str = "content") -> Any:
        url = f"{self.get_base_url()}/periodic/{period}/"

        def call_fn() -> Any:
            headers = self._get_headers()
            if type == "metadata":
                headers["Accept"] = "application/vnd.olrapi.note+json"
            response = requests.get(
                url, headers=headers, verify=self.verify_ssl, timeout=self.timeout
            )
            response.raise_for_status()
            return response.text

        return self._safe_call(call_fn)

    def get_recent_periodic_notes(
        self, period: str, limit: int = 5, include_content: bool = False
    ) -> Any:
        # The plugin has no "list recent" endpoint; reconstruct via Dataview DQL.
        if period == "daily":
            # Dataview sets file.day for all date-named notes
            dql = f"TABLE file.mtime\nWHERE file.day\nSORT file.day DESC\nLIMIT {limit}"
        else:
            # Discover the folder from the current periodic note, then scope the query
            folder = ""
            try:
                meta_headers = self._get_headers() | {"Accept": "application/vnd.olrapi.note+json"}
                r = requests.get(
                    f"{self.get_base_url()}/periodic/{period}/",
                    headers=meta_headers,
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                )
                r.raise_for_status()
                path: str = r.json().get("path", "")
                folder = path.rsplit("/", 1)[0] if "/" in path else ""
            except Exception:
                pass  # fall back to unscoped query
            where = f'contains(file.folder, "{folder}")' if folder else "file.mtime"
            dql = f"TABLE file.mtime\nWHERE {where}\nSORT file.mtime DESC\nLIMIT {limit}"

        url = f"{self.get_base_url()}/search/"
        headers = self._get_headers() | {"Content-Type": "application/vnd.olrapi.dataview.dql+txt"}

        def call_fn() -> Any:
            response = requests.post(
                url,
                headers=headers,
                data=dql.encode("utf-8"),
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            results = response.json()
            if include_content and isinstance(results, list):
                for item in results:
                    filepath = str(item.get("filename", ""))
                    if filepath:
                        try:
                            item["content"] = self.get_file_contents(filepath)
                        except Exception:
                            item["content"] = None
            return results

        return self._safe_call(call_fn)

    def get_recent_changes(self, limit: int = 10, days: int = 90) -> Any:
        dql_query = "\n".join(
            [
                "TABLE file.mtime",
                f"WHERE file.mtime >= date(today) - dur({days} days)",
                "SORT file.mtime DESC",
                f"LIMIT {limit}",
            ]
        )
        url = f"{self.get_base_url()}/search/"
        headers = self._get_headers() | {"Content-Type": "application/vnd.olrapi.dataview.dql+txt"}

        def call_fn() -> Any:
            response = requests.post(
                url,
                headers=headers,
                data=dql_query.encode("utf-8"),
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        return self._safe_call(call_fn)
