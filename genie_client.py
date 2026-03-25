"""Genie REST API wrapper."""

import asyncio
import logging
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class GenieClient:
    """Calls Genie API using per-user OAuth tokens."""

    def __init__(self, host: str, space_id: str):
        self.host = host
        self.space_id = space_id
        self._base = f"{host}/api/2.0/genie/spaces/{space_id}"

    def _headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def ask(self, token: str, question: str) -> Dict[str, Any]:
        """Start a new Genie conversation."""
        resp = requests.post(
            f"{self._base}/start-conversation",
            headers=self._headers(token),
            json={"content": question},
        )
        resp.raise_for_status()
        data = resp.json()

        conversation_id = data["conversation_id"]
        message_id = data["message_id"]
        logger.info(f"Genie conversation started: {conversation_id}")

        msg = await self._poll(token, conversation_id, message_id)
        return self._format_response(token, conversation_id, msg)

    async def followup(
        self, token: str, conversation_id: str, question: str
    ) -> Dict[str, Any]:
        """Send a follow-up in an existing conversation."""
        resp = requests.post(
            f"{self._base}/conversations/{conversation_id}/messages",
            headers=self._headers(token),
            json={"content": question},
        )
        resp.raise_for_status()
        data = resp.json()
        message_id = data["message_id"]

        msg = await self._poll(token, conversation_id, message_id)
        return self._format_response(token, conversation_id, msg)

    def get_conversation_messages(
        self, token: str, conversation_id: str
    ) -> List[Dict[str, Any]]:
        """Get all messages in a conversation."""
        resp = requests.get(
            f"{self._base}/conversations/{conversation_id}/messages",
            headers=self._headers(token),
        )
        resp.raise_for_status()
        return resp.json().get("messages", [])

    async def _poll(
        self, token: str, conversation_id: str, message_id: str
    ) -> Dict[str, Any]:
        """Poll until the message is completed or failed."""
        for _ in range(60):
            resp = requests.get(
                f"{self._base}/conversations/{conversation_id}/messages/{message_id}",
                headers=self._headers(token),
            )
            resp.raise_for_status()
            msg = resp.json()
            status = msg.get("status")

            if status == "COMPLETED":
                return msg
            if status in ("FAILED", "CANCELLED"):
                error = msg.get("error", {})
                error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                raise RuntimeError(f"Genie query failed: {error_msg}")

            await asyncio.sleep(2)

        raise TimeoutError("Genie response timed out after 120s")

    def _format_response(
        self, token: str, conversation_id: str, msg: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract text, SQL, table data, and chart hints from the Genie message."""
        result: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "message_id": msg.get("id") or msg.get("message_id"),
            "text": None,
            "sql": None,
            "sql_description": None,
            "columns": [],
            "rows": [],
            "column_types": [],
            "suggested_questions": [],
            "chart": None,
            "error": None,
        }

        for att in msg.get("attachments", []):
            # Text content
            text = att.get("text")
            if text:
                result["text"] = text.get("content")

            # SQL query
            query = att.get("query")
            if query:
                result["sql"] = query.get("query")
                result["sql_description"] = query.get("description")

                # Fetch query results
                attachment_id = att.get("attachment_id")
                if attachment_id:
                    table = self._get_query_result(
                        token, conversation_id,
                        msg.get("id") or msg.get("message_id"),
                        attachment_id,
                    )
                    if table:
                        result["columns"] = table["columns"]
                        result["rows"] = table["rows"]
                        result["column_types"] = table["column_types"]
                        result["chart"] = self._infer_chart(
                            table["columns"], table["column_types"], table["rows"]
                        )

            # Suggested questions
            sq = att.get("suggested_questions")
            if sq:
                result["suggested_questions"] = sq.get("questions", sq)
            # Alternative key
            suggestions = att.get("suggestions")
            if suggestions:
                result["suggested_questions"] = suggestions

        return result

    def _get_query_result(
        self,
        token: str,
        conversation_id: str,
        message_id: str,
        attachment_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch SQL query results from an attachment."""
        try:
            resp = requests.get(
                f"{self._base}/conversations/{conversation_id}"
                f"/messages/{message_id}/query-result/{attachment_id}",
                headers=self._headers(token),
            )
            resp.raise_for_status()
            data = resp.json()

            statement = data.get("statement_response", data)
            manifest = statement.get("manifest", {})
            schema_cols = manifest.get("schema", {}).get("columns", [])
            columns = [c["name"] for c in schema_cols]
            column_types = [c.get("type_name", "STRING") for c in schema_cols]
            rows = statement.get("result", {}).get("data_array", [])

            return {"columns": columns, "column_types": column_types, "rows": rows}
        except Exception as e:
            logger.warning(f"Failed to fetch query result: {e}")
            return None

    def _infer_chart(
        self,
        columns: List[str],
        column_types: List[str],
        rows: List[List],
    ) -> Optional[Dict[str, Any]]:
        """Infer a chart configuration from the query result schema.

        Returns a hint dict for the frontend to render a chart, or None
        if the data isn't suitable for charting.
        """
        if not columns or not rows or len(columns) < 2:
            return None

        numeric_types = {"INT", "BIGINT", "FLOAT", "DOUBLE", "DECIMAL", "LONG", "SHORT", "BYTE"}

        # Find label column (first non-numeric) and value columns (numeric)
        label_idx = None
        value_indices = []
        for i, ct in enumerate(column_types):
            type_upper = ct.upper()
            if any(nt in type_upper for nt in numeric_types):
                value_indices.append(i)
            elif label_idx is None:
                label_idx = i

        if not value_indices:
            return None

        # Default label to first column if no string column found
        if label_idx is None:
            label_idx = 0

        # Cap rows for chart rendering
        chart_rows = rows[:100]
        labels = [r[label_idx] if r[label_idx] is not None else "" for r in chart_rows]

        datasets = []
        for vi in value_indices:
            values = []
            for r in chart_rows:
                try:
                    values.append(float(r[vi]) if r[vi] is not None else 0)
                except (ValueError, TypeError):
                    values.append(0)
            datasets.append({
                "label": columns[vi],
                "data": values,
            })

        # Choose chart type
        num_labels = len(set(labels))
        chart_type = "bar"
        if num_labels > 20:
            chart_type = "line"
        elif num_labels <= 6 and len(value_indices) == 1:
            chart_type = "pie"

        return {
            "type": chart_type,
            "labels": labels,
            "datasets": datasets,
        }
