# Downstream Open WebUI

This fork is the source of truth for the Dissipative Memory adapter, HUD and client customizations.
Dissipative Core, deployable Functions/Tools, build exports and qualification belong to [Dissipative Memory](https://github.com/harrywenjie/dissipative), locally `E:/dissipative`. PrivateOperations retains host inventory, credentials and operational records.

The initial downstream commit imports the qualified Adapter 4.14 on upstream v0.11.3 byte-for-byte.
Upgrades merge a fixed upstream release into a new branch, resolve conflicts, run the downstream and integration gates, then freeze an immutable release commit. Never rewrite published release history.

The Dissipative repository carries machine-generated patch/overlay exports for offline qualification. They are not editable sources; changes start in this fork and are exported from a pinned commit.

The `dissipative-adapter-4.17` source candidate is not deployed. It adds an administrator-only
internal inference endpoint at `/api/v1/dissipative/internal/chat/completions`. The endpoint
uses reviewed Qwen role/prompt/parameter pins, retains model access checks, skips ordinary
chat customization and verifies the final provider payload. Existing chat routes keep their
normal behavior. The source contract is not evidence of live provider qualification.

`backend/open_webui/utils/dissipative_model_contract_data.py` is generated from Dissipative's
reviewed model qualification registry and invocation profile with
`python scripts/sync-model-qualification.py --source E:/open-webui --write` from that repo.
Commit the generated module with its consumer, then regenerate Dissipative's pinned fork
exports. Never edit a generated pin to bypass a failed role check.
