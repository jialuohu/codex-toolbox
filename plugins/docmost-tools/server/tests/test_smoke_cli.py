from __future__ import annotations

import json
import unittest
from io import StringIO
from unittest import mock

from docmost_tools import smoke_cli
from docmost_tools.models import CurrentUser, CursorPage, OperationResult, Space, User, Workspace
from docmost_tools.profile import ProfilePathError


class SmokeCliTests(unittest.TestCase):
    def test_main_emits_success_only_after_identity_and_spaces(self) -> None:
        identity = CurrentUser(user=User(id="user"), workspace=Workspace(id="workspace"))
        spaces = CursorPage[Space](items=[Space(id="space")])

        class Client:
            def current_user(self) -> OperationResult[CurrentUser]:
                return OperationResult[CurrentUser](ok=True, data=identity)

            def list_spaces(
                self, *, limit: int, cursor: str | None = None
            ) -> OperationResult[CursorPage[Space]]:
                self.limit = limit
                self.cursor = cursor
                return OperationResult[CursorPage[Space]](ok=True, data=spaces)

            def close(self) -> None:
                self.closed = True

        client = Client()
        state = mock.Mock(client=client, startup_error=None)
        output = StringIO()
        with mock.patch.object(smoke_cli, "bootstrap_runtime", return_value=state):
            with mock.patch.object(smoke_cli, "DocmostSettings") as settings:
                settings.model_validate.return_value = mock.sentinel.settings
                with mock.patch.object(
                    smoke_cli, "profile_paths", return_value=mock.sentinel.paths
                ):
                    exit_code = smoke_cli.main(output=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(client.limit, 1)
        self.assertIsNone(client.cursor)
        state.close.assert_called_once()

    def test_configuration_failure_is_redacted(self) -> None:
        output = StringIO()
        with mock.patch.object(
            smoke_cli, "profile_paths", side_effect=ProfilePathError("https://private.example.test")
        ):
            exit_code = smoke_cli.main(output=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["error"]["code"], "configuration_invalid")
        self.assertNotIn("private.example.test", output.getvalue())
