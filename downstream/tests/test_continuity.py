"""Host revision and admission regressions that the Core transport fixtures cannot exercise."""

import copy
import json
from types import SimpleNamespace
import unittest

from open_webui.utils.dissipative_continuity import project, ContinuityChat
from open_webui.utils.dissipative_source import ChatMemoryProjectionError


class WebUISourceTests(unittest.TestCase):
    def setUp(self):
        self.scope = dict(instance_id="isolated-webui", owner_id="owner", chat_id="chat")
        self.rows = {
            "u": dict(id="u", parentId=None, role="user", content="confirmed private fixture", user_id="owner"),
            "a": dict(id="a", parentId="u", role="assistant", content="completed reply", model="test", done=True),
        }
        self.chat = SimpleNamespace(id="chat", user_id="owner", current_message_id="a", share_id=None, variables={},
            dissipative_source_state=None, chat={"history": {"currentId": "a", "messages": self.rows}})

    def sync(self, grants=()):
        return project(self.chat, self.scope, grants)

    def test_exact_restart_and_completed_rewrite(self):
        first, host = self.sync()
        self.assertNotIn("confirmed private fixture", json.dumps(self.chat.dissipative_source_state))
        self.chat.dissipative_source_state = json.loads(json.dumps(self.chat.dissipative_source_state))
        self.assertEqual(self.sync(), (first, host))
        self.rows["a"]["content"] += " continued"
        changed, _ = self.sync()
        self.assertGreater(changed["lineageRevision"], first["lineageRevision"])
        self.assertEqual(changed["sources"][1]["binding"]["sourceVersion"], 2)
        self.assertEqual(self.sync()[0], changed)

    def test_branch_deletion_and_grants(self):
        first, _ = self.sync()
        self.rows["b"] = dict(self.rows["a"], id="b", content="replacement")
        self.chat.current_message_id = "b"
        branch, _ = self.sync()
        self.assertNotIn("a", branch["coverage"])
        self.assertGreater(branch["lineageRevision"], first["lineageRevision"])
        del self.rows["a"]
        revoked, _ = self.sync(["updated-grant"])
        self.assertGreater(revoked["authorizationRevision"], branch["authorizationRevision"])
        self.assertEqual(revoked["events"][0]["reason"], "SOURCE_DELETED")
        self.rows["a"] = dict(self.rows["b"], id="a")
        self.chat.current_message_id = "a"
        with self.assertRaises(ChatMemoryProjectionError):
            self.sync()

    def test_same_role_pending_and_host_owned_attribution(self):
        self.rows["next"] = dict(id="next", role="assistant", content="another", parentId="a", done=True,
                                 evidence_class="USER_EXPLICIT", producer_id="forged")
        self.chat.current_message_id = "next"
        snapshot, host = self.sync()
        client = ContinuityChat(None, self.scope, snapshot, host, {m["message_id"]: m["message_id"] for m in host["messages"]})
        self.assertEqual([r["stableSourceId"] for r in client.refs()], ["u", "a", "next"])
        self.assertEqual([r["stableSourceId"] for r in client.refs("next")], ["next"])
        self.assertEqual(host["messages"][-1]["evidence_class"], "ORDINARY")
        self.assertNotEqual(host["messages"][-1]["producer_id"], "forged")
        self.rows["next"]["done"] = False
        snapshot, host = self.sync()
        self.assertEqual(ContinuityChat(None, self.scope, snapshot, host, client.ids).refs("next"), [])

    def test_off_suppresses_prose_and_preserves_versions(self):
        self.sync()
        previous = copy.deepcopy(self.chat.dissipative_source_state["versions"])
        self.chat.variables["memory_access_mode"] = "OFF"
        snapshot, host = self.sync()
        self.assertEqual((snapshot["sources"], host["messages"]), ([], []))
        self.assertEqual(self.chat.dissipative_source_state["versions"], previous)
