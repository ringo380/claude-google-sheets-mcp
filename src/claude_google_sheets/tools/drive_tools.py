"""Drive API tools for spreadsheet discovery and management."""

import json
import logging
from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError
from mcp.types import TextContent, Tool

from ..auth.oauth_manager import GoogleSheetsAuth
from ..core.exceptions import AuthenticationError, DriveAPIError
from ..core.tool_handler import SheetsToolHandler

logger = logging.getLogger(__name__)


class ListSpreadsheetsHandler(SheetsToolHandler):
    """Handler for listing all Google Sheets in user's Drive."""

    def __init__(self, auth: GoogleSheetsAuth) -> None:
        super().__init__(
            name="list_spreadsheets",
            description="List all Google Sheets in the user's Google Drive",
        )
        self.auth = auth

    def get_tool_definition(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of spreadsheets to return (default: 100)",
                        "default": 100,
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query to filter spreadsheets by name or content",
                        "default": "",
                    },
                    "include_shared": {
                        "type": "boolean",
                        "description": "Include spreadsheets shared with the user (default: true)",
                        "default": True,
                    },
                },
            },
        )

    async def execute(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Execute the list spreadsheets operation."""
        try:
            max_results = arguments.get("max_results", 100)
            query = arguments.get("query", "")
            include_shared = arguments.get("include_shared", True)

            drive_service = self.auth.get_drive_service()

            # Build the search query
            search_parts = ["mimeType='application/vnd.google-apps.spreadsheet'"]

            if not include_shared:
                search_parts.append("'me' in owners")

            search_parts.append("trashed=false")

            if query:
                search_parts.append(f"name contains '{query}'")

            search_query = " and ".join(search_parts)

            # Execute the search
            results = (
                drive_service.files()
                .list(
                    q=search_query,
                    pageSize=min(max_results, 1000),
                    fields="nextPageToken, files(id, name, createdTime, modifiedTime, owners, shared, webViewLink, size)",
                )
                .execute()
            )

            files = results.get("files", [])

            if not files:
                return self.format_success_response("No spreadsheets found.")

            # Format the results
            spreadsheets = []
            for file in files:
                owners = file.get("owners", [])
                owner_names = [owner.get("displayName", "Unknown") for owner in owners]

                spreadsheet_info = {
                    "id": file["id"],
                    "name": file["name"],
                    "created": file.get("createdTime", "Unknown"),
                    "modified": file.get("modifiedTime", "Unknown"),
                    "owners": owner_names,
                    "is_shared": file.get("shared", False),
                    "web_link": file.get("webViewLink", ""),
                    "size": file.get("size", "0"),
                }
                spreadsheets.append(spreadsheet_info)

            # Sort by modification time (most recent first)
            spreadsheets.sort(key=lambda x: x["modified"], reverse=True)

            response_data = {
                "total_found": len(spreadsheets),
                "spreadsheets": spreadsheets[:max_results],
            }

            return self.format_success_response(
                json.dumps(response_data, indent=2),
                f"Found {len(spreadsheets)} spreadsheet(s)",
            )

        except HttpError as e:
            raise DriveAPIError(f"Drive API error: {e.reason}", e.resp.status)
        except Exception as e:
            return self.format_error_response(e)


class SearchSpreadsheetsHandler(SheetsToolHandler):
    """Handler for searching spreadsheets by advanced criteria."""

    def __init__(self, auth: GoogleSheetsAuth) -> None:
        super().__init__(
            name="search_spreadsheets",
            description="Search for spreadsheets with advanced filtering options",
        )
        self.auth = auth

    def get_tool_definition(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "name_contains": {
                        "type": "string",
                        "description": "Search for spreadsheets with names containing this text",
                    },
                    "owner_email": {
                        "type": "string",
                        "description": "Filter by owner email address",
                    },
                    "created_after": {
                        "type": "string",
                        "description": "Find spreadsheets created after this date (ISO format: YYYY-MM-DD)",
                    },
                    "modified_after": {
                        "type": "string",
                        "description": "Find spreadsheets modified after this date (ISO format: YYYY-MM-DD)",
                    },
                    "shared_only": {
                        "type": "boolean",
                        "description": "Only return shared spreadsheets",
                        "default": False,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 50,
                    },
                },
            },
        )

    async def execute(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Execute the search spreadsheets operation."""
        try:
            name_contains = arguments.get("name_contains")
            owner_email = arguments.get("owner_email")
            created_after = arguments.get("created_after")
            modified_after = arguments.get("modified_after")
            shared_only = arguments.get("shared_only", False)
            max_results = arguments.get("max_results", 50)

            drive_service = self.auth.get_drive_service()

            # Build the search query
            search_parts = ["mimeType='application/vnd.google-apps.spreadsheet'"]
            search_parts.append("trashed=false")

            if name_contains:
                search_parts.append(f"name contains '{name_contains}'")

            if owner_email:
                search_parts.append(f"'{owner_email}' in owners")

            if created_after:
                search_parts.append(f"createdTime > '{created_after}T00:00:00'")

            if modified_after:
                search_parts.append(f"modifiedTime > '{modified_after}T00:00:00'")

            if shared_only:
                search_parts.append("sharedWithMe=true")

            search_query = " and ".join(search_parts)

            # Execute the search
            results = (
                drive_service.files()
                .list(
                    q=search_query,
                    pageSize=min(max_results, 1000),
                    fields="files(id, name, createdTime, modifiedTime, owners, shared, webViewLink, parents)",
                )
                .execute()
            )

            files = results.get("files", [])

            if not files:
                return self.format_success_response(
                    "No spreadsheets found matching the criteria."
                )

            # Format the results
            spreadsheets = []
            for file in files:
                owners = file.get("owners", [])
                owner_info = [
                    (owner.get("displayName", "Unknown"), owner.get("emailAddress", ""))
                    for owner in owners
                ]

                spreadsheet_info = {
                    "id": file["id"],
                    "name": file["name"],
                    "created": file.get("createdTime", "Unknown"),
                    "modified": file.get("modifiedTime", "Unknown"),
                    "owners": owner_info,
                    "is_shared": file.get("shared", False),
                    "web_link": file.get("webViewLink", ""),
                    "parent_folders": file.get("parents", []),
                }
                spreadsheets.append(spreadsheet_info)

            response_data = {
                "search_criteria": {
                    "name_contains": name_contains,
                    "owner_email": owner_email,
                    "created_after": created_after,
                    "modified_after": modified_after,
                    "shared_only": shared_only,
                },
                "total_found": len(spreadsheets),
                "spreadsheets": spreadsheets,
            }

            return self.format_success_response(
                json.dumps(response_data, indent=2),
                f"Found {len(spreadsheets)} spreadsheet(s) matching criteria",
            )

        except HttpError as e:
            raise DriveAPIError(f"Drive API error: {e.reason}", e.resp.status)
        except Exception as e:
            return self.format_error_response(e)


class GetSpreadsheetInfoHandler(SheetsToolHandler):
    """Handler for getting detailed information about a specific spreadsheet."""

    def __init__(self, auth: GoogleSheetsAuth) -> None:
        super().__init__(
            name="get_spreadsheet_info",
            description="Get detailed metadata about a specific spreadsheet",
        )
        self.auth = auth

    def get_tool_definition(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "spreadsheet_id": {
                        "type": "string",
                        "description": "The ID of the spreadsheet to get information about",
                    }
                },
                "required": ["spreadsheet_id"],
            },
        )

    async def execute(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """Execute the get spreadsheet info operation."""
        try:
            self.validate_arguments(arguments, ["spreadsheet_id"])
            spreadsheet_id = arguments["spreadsheet_id"]

            # Get info from Drive API
            drive_service = self.auth.get_drive_service()
            drive_info = (
                drive_service.files()
                .get(
                    fileId=spreadsheet_id,
                    fields="id, name, createdTime, modifiedTime, owners, shared, webViewLink, size, parents",
                )
                .execute()
            )

            # Get detailed info from Sheets API
            sheets_service = self.auth.get_sheets_service()
            sheets_info = (
                sheets_service.spreadsheets()
                .get(
                    spreadsheetId=spreadsheet_id, fields="properties,sheets.properties"
                )
                .execute()
            )

            # Combine the information
            owners = drive_info.get("owners", [])
            owner_info = [
                (owner.get("displayName", "Unknown"), owner.get("emailAddress", ""))
                for owner in owners
            ]

            sheets_list = []
            for sheet in sheets_info.get("sheets", []):
                sheet_props = sheet.get("properties", {})
                sheets_list.append(
                    {
                        "sheet_id": sheet_props.get("sheetId"),
                        "title": sheet_props.get("title"),
                        "sheet_type": sheet_props.get("sheetType", "GRID"),
                        "grid_properties": sheet_props.get("gridProperties", {}),
                        "hidden": sheet_props.get("hidden", False),
                        "tab_color": sheet_props.get("tabColor", {}),
                    }
                )

            spreadsheet_info = {
                "id": drive_info["id"],
                "name": drive_info["name"],
                "created": drive_info.get("createdTime", "Unknown"),
                "modified": drive_info.get("modifiedTime", "Unknown"),
                "owners": owner_info,
                "is_shared": drive_info.get("shared", False),
                "web_link": drive_info.get("webViewLink", ""),
                "size": drive_info.get("size", "0"),
                "parent_folders": drive_info.get("parents", []),
                "sheets": sheets_list,
                "properties": sheets_info.get("properties", {}),
            }

            return self.format_success_response(
                json.dumps(spreadsheet_info, indent=2),
                f"Retrieved information for spreadsheet: {drive_info['name']}",
            )

        except HttpError as e:
            if e.resp.status == 404:
                raise DriveAPIError("Spreadsheet not found", 404)
            else:
                raise DriveAPIError(f"Drive API error: {e.reason}", e.resp.status)
        except Exception as e:
            return self.format_error_response(e)


# Registry of all drive tool handlers
DRIVE_HANDLERS = [
    ListSpreadsheetsHandler,
    SearchSpreadsheetsHandler,
    GetSpreadsheetInfoHandler,
]
