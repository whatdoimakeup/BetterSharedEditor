/**
 * User list component showing connected users.
 */

import { observer } from "mobx-react-lite";
import { editorStore } from "@/stores/rootStore";

const UserList = observer(() => {
  const users = editorStore.connectedUsersList;
  const userCount = editorStore.activeUserCount;

  return (
    <div className="user-list">
      <div className="user-count">
        <span className="user-count-badge">{userCount}</span>
        <span className="user-count-label">
          {userCount === 1 ? "user" : "users"}
        </span>
      </div>
      {users.length > 0 && (
        <div className="user-items">
          {users.map((user) => (
            <div
              key={user.clientId}
              className="user-item"
              title={user.displayName}
            >
              <span
                className="user-color-dot"
                style={{ backgroundColor: user.color }}
              />
              <span className="user-name">{user.displayName}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

export default UserList;
