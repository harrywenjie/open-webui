# Downstream Open WebUI

This fork is the source of truth for the Dissipative Memory adapter, HUD and client customizations.
Dissipative Core, deployable Functions/Tools, build exports and qualification belong to [Dissipative Memory](https://github.com/harrywenjie/dissipative), locally `E:/dissipative`. PrivateOperations retains host inventory, credentials and operational records.

The initial downstream commit imports the qualified Adapter 4.14 on upstream v0.11.3 byte-for-byte.
Upgrades merge a fixed upstream release into a new branch, resolve conflicts, run the downstream and integration gates, then freeze an immutable release commit. Never rewrite published release history.

The Dissipative repository carries machine-generated patch/overlay exports for offline qualification. They are not editable sources; changes start in this fork and are exported from a pinned commit.

The `dissipative-adapter-4.19` source candidate is not deployed. It removes the uninstalled
4.17 internal inference proxy and its generated role contract. Dissipative owns its model
connection and calls its configured provider directly. This fork adapts to the memory API;
it does not provide model routing, parameters or credentials for Core inference.

Ordinary chat continues to use WebUI's own model configuration and connection. Memory
source synchronization, authenticated management, HUD and publication integration remain
client responsibilities. Future clients are outside this change's scope.

The HUD displays Core's current-chat/current-branch processing coverage projection.
Archive storage and Curator maintenance counts remain separate; this observational
summary never claims source verification or exhaustive recall. Older Core versions
without the additive coverage field keep their existing display.
