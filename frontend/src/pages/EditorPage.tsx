import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { observer } from "mobx-react-lite";
import { editorStore } from "@/stores/rootStore";
import UserList from "@/components/UserList";
import ConnectionStatus from "@/components/ConnectionStatus";
import SaveStatus from "@/components/SaveStatus";
import "@/styles/EditorPage.css";
import AceEditorComponent from "@/components/AceEditor";

const EditorPage = observer(() => {
  const { roomId } = useParams<{ roomId: string }>();
  const navigate = useNavigate();
  const roomIdNum = Number.parseInt(roomId || "0", 10);

  useEffect(() => {
    if (!roomIdNum) return;

    void editorStore.initializeRoom(roomIdNum);

    return () => {
      editorStore.destroy();
    };
  }, [roomIdNum]);

  if (!roomIdNum) {
    return <div className="error">Invalid room ID</div>;
  }

  return (
    <div className="editor-page">
      <header className="editor-header">
        <div className="editor-header-left">
          <button className="btn btn-secondary" onClick={() => navigate("/")}>
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

      {editorStore.connectionError && (
        <div className="error-banner">{editorStore.connectionError}</div>
      )}

      <div className="editor-container">
        {editorStore.isInitializing ? (
          <div className="loading">Loading editor...</div>
        ) : (
          <AceEditorComponent yText={editorStore.yText} />
        )}
      </div>
    </div>
  );
});

export default EditorPage;
