/**
 * Room list page component.
 *
 * Displays existing rooms and allows creating new ones.
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { observer } from "mobx-react-lite";
import { roomStore } from "@/stores/rootStore";
import "@/styles/RoomListPage.css";

const RoomListPage = observer(() => {
  const navigate = useNavigate();
  const [newRoomName, setNewRoomName] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    roomStore.loadRooms();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRoomName.trim()) return;

    setIsCreating(true);
    const room = await roomStore.createRoom(newRoomName.trim());
    setIsCreating(false);

    if (room) {
      setNewRoomName("");
      navigate(`/room/${room.id}`);
    }
  };

  const handleJoin = (roomId: number) => {
    navigate(`/room/${roomId}`);
  };

  const handleDelete = async (e: React.MouseEvent, roomId: number) => {
    e.stopPropagation();
    if (confirm("Delete this room? This cannot be undone.")) {
      await roomStore.removeRoom(roomId);
    }
  };

  return (
    <div className="room-list-page">
      <header className="room-list-header">
        <h1>Better Shared Editor</h1>
        <p>Collaborative code editing with Yjs</p>
      </header>

      <div className="container">
        {/* Create room form */}
        <form onSubmit={handleCreate} className="create-room-form card">
          <h2>Create New Room</h2>
          <div className="form-row">
            <input
              type="text"
              placeholder="Room name..."
              value={newRoomName}
              onChange={(e) => setNewRoomName(e.target.value)}
              className="room-name-input"
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isCreating || !newRoomName.trim()}
            >
              {isCreating ? "Creating..." : "Create & Join"}
            </button>
          </div>
        </form>

        {/* Error message */}
        {roomStore.error && (
          <div className="error-banner">{roomStore.error}</div>
        )}

        {/* Room list */}
        <div className="rooms-section">
          <h2>Existing Rooms</h2>

          {roomStore.isLoading && (
            <div className="loading">Loading rooms...</div>
          )}

          {!roomStore.isLoading && roomStore.rooms.length === 0 && (
            <div className="empty-state">
              <p>No rooms yet. Create one above to get started!</p>
            </div>
          )}

          <div className="rooms-grid">
            {roomStore.rooms.map((room) => (
              <div
                key={room.id}
                className="room-card card"
                onClick={() => handleJoin(room.id)}
              >
                <div className="room-card-header">
                  <h3>{room.name}</h3>
                  <button
                    className="btn-delete"
                    onClick={(e) => handleDelete(e, room.id)}
                    title="Delete room"
                  >
                    ✕
                  </button>
                </div>
                <div className="room-card-meta">
                  <span className="room-id">#{room.id}</span>
                  {room.has_state && (
                    <span className="badge badge-success">Has state</span>
                  )}
                  {room.has_content && (
                    <span className="badge badge-info">Has content</span>
                  )}
                </div>
                <div className="room-card-footer">
                  <span>Updated: {new Date(room.updated_at).toLocaleString()}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
});

export default RoomListPage;
