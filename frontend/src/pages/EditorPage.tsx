/**
 * Editor page component.
 *
 * Contains the Ace editor with Yjs collaboration, user list, and connection status.
 */

import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { observer } from "mobx-react-lite";
import * as Y from "yjs";
import { editorStore } from "@/stores/rootStore";
import MonacoEditor from "@/components/MonacoEditor";
import UserList from "@/components/UserList";
import ConnectionStatus from "@/components/ConnectionStatus";
import SaveStatus from "@/components/SaveStatus";
import { getRoomState } from "@/api/client";
import { decode_yjs_state } from "@/yjs/utils";
import "@/styles/EditorPage.css";

const EditorPage = observer(() => {
  const { roomId } = useParams<{ roomId: string }>();
  const navigate = useNavigate();

  const roomIdNum = parseInt(roomId || "0", 10);

  // Initialize editor store and provider
  useEffect(() => {
    if (!roomIdNum) return;

    // Reset document for new room (creates fresh yDoc)
    editorStore.resetDocument();
    editorStore.setConnectionStatus("connecting");

    const init = async () => {
      try {
        // Load persisted Yjs state from DB
        try {
          const state = await getRoomState(roomIdNum);
          if (state.yjs_state) {
            Y.applyUpdate(editorStore.yDoc, decode_yjs_state(state.yjs_state));
          }
        } catch {
          // Room has no saved state yet — start empty
        }

        // Import and create the Centrifugo provider
        const { createCentrifugoProvider } =
          await import("../yjs/CentrifugoProvider");

        const provider = createCentrifugoProvider(
          roomIdNum,
          editorStore.yDoc,
          editorStore,
        );

        editorStore.setProvider(provider);
      } catch (e: any) {
        console.error("Failed to initialize editor:", e);
        editorStore.setConnectionStatus(
          "error",
          e.message || "Failed to connect",
        );
      }
    };

    init();

    return () => {
      if (editorStore.provider) {
        editorStore.provider.destroy();
        editorStore.setProvider(null);
      }
    };
  }, [roomIdNum]);
  const handleBack = () => {
    navigate("/");
  };

  if (!roomIdNum) {
    return <div className="error">Invalid room ID</div>;
  }

  return (
    <div className="editor-page">
      {/* Top bar */}
      <header className="editor-header">
        <div className="editor-header-left">
          <button className="btn btn-secondary" onClick={handleBack}>
            ← Back
          </button>
          <span className="room-title">Room #{roomIdNum}</span>
        </div>
        <div className="editor-header-right">
          <SaveStatus />
          <ConnectionStatus />
          <UserList />
        </div>
      </header>

      {/* Error banner */}
      {editorStore.connectionError && (
        <div className="error-banner">{editorStore.connectionError}</div>
      )}

      {/* Editor area */}
      <div className="editor-container">
        <MonacoEditor roomId={roomIdNum} />
      </div>
    </div>
  );
});

export default EditorPage;
