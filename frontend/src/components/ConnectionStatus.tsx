/**
 * Connection status indicator component.
 */

import { observer } from "mobx-react-lite";
import { editorStore } from "@/stores/rootStore";

const ConnectionStatus = observer(() => {
  const status = editorStore.connectionStatus;

  const statusConfig: Record<string, { label: string; className: string }> = {
    disconnected: { label: "Disconnected", className: "status-disconnected" },
    connecting: { label: "Connecting...", className: "status-connecting" },
    connected: { label: "Connected", className: "status-connected" },
    error: { label: "Connection Error", className: "status-error" },
  };

  const config = statusConfig[status] || statusConfig.disconnected;

  return (
    <div className={`connection-status ${config.className}`}>
      <span className="status-dot" />
      <span className="status-label">{config.label}</span>
    </div>
  );
});

export default ConnectionStatus;
